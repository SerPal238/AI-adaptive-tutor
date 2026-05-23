# backend/services/task_service.py
import ast
import httpx
import json
from sqlmodel import select
from datetime import datetime
from sqlmodel.ext.asyncio.session import AsyncSession
from db.models import GeneratedTask, TopicMastery, Attempt
from llm.base import LLMProvider, LLMConfig, TaskOutput
from services.adaptation import get_or_create_mastery, mastery_to_difficulty, update_mastery

TASK_PROMPT = """Ты — персональный репетитор по Python. Сгенерируй ИНДИВИДУАЛЬНОЕ задание.

КОНТЕКСТ СТУДЕНТА (ПО ЭТОЙ ТЕМЕ):
{tutor_context_block}

ИСТОРИЯ ПОСЛЕДНИХ ЗАДАНИЙ (СТРОГО НЕ ПОВТОРЯЙ ИХ):
{history_block}

ПАРАМЕТРЫ:
Тема: {topic}
Базовый уровень: {difficulty}

ИНСТРУКЦИИ:
1. Адаптируй фокус задания под контекст (слабые места, стиль обучения, паузы).
2. Если указаны слабые места — включи их мягкую проверку в формулировку или ожидаемый ответ.
3. Если студент давно не практиковался — начни с повторения базы.
4. Если есть серия практики (streak) — похвали в explanation или чуть усложни логику.
5. ОТВЕТЬ СТРОГО В ФОРМАТЕ JSON. БЕЗ markdown, БЕЗ текста до/после JSON.
6. Поля ОБЯЗАТЕЛЬНЫ: question, expected_answer, answer_type, difficulty, explanation.

Пример корректного JSON:
{{
  "question": "Напишите код, который...",
  "expected_answer": "print('...')",
  "answer_type": "code",
  "difficulty": "easy",
  "explanation": "Функция print() выводит..."
}}

Генерируй задание:"""

VERIFY_PROMPT = """Ты проверяешь ЛОГИКУ кода на Python. Синтаксис уже проверен и ВЕРЕН.

ЗАДАНИЕ:
{question}

ОЖИДАЕМЫЙ ОТВЕТ:
{expected_answer}

ОТВЕТ СТУДЕНТА:
{student_answer}

ОТВЕТЬ СТРОГО В ФОРМАТЕ JSON:
{{
  "is_correct": true/false,
  "explanation": "Краткое объяснение на русском",
  "weakness": "конкретная концепция ИЛИ 'none'"
}}

✅ ПРИНИМАЙ КАК ПРАВИЛЬНЫЙ, ЕСЛИ:
- Логика соответствует заданию
- Синтаксис корректный

🚫 СТРОГО ЗАПРЕЩЕНО ПРОВЕРЯТЬ:
- Типы кавычек: 'text' = "text" — ОБА ВЕРНЫ!
- Пробелы: print(x,y,z) = print(x, y, z)
- Имена переменных: x, a, my_var — ВСЁ ОК

ПРИМЕРЫ:
Задание: "Выведите 'Hello'"
Эталон: "print('Hello')"
Студент: "print("Hello")"
Вердикт: is_correct: true (кавычки не важны!)

Задание: "Создайте переменную"
Эталон: "x = 5"
Студент: "a = 5"
Вердикт: is_correct: true (имя не важно)

Если ответ правильный → weakness: "none"
Если неправильный → weakness: "logic_error" или "missing_function" и т.д.

Проверь ответ:"""
class TaskGenerationService:
    def __init__(self, llm: LLMProvider, session: AsyncSession):
        self.llm = llm
        self.session = session

    async def generate_adaptive_task(self, student_id: int, topic_id: int, topic_name: str) -> dict:
        # 1. Получаем полную запись mastery (с новыми полями)
        stmt = select(TopicMastery).where(
            TopicMastery.student_id == student_id,
            TopicMastery.topic_id == topic_id
        )
        result = await self.session.exec(stmt)
        mastery = result.first() or TopicMastery(student_id=student_id, topic_id=topic_id, mastery_level=0.0)

        if not mastery:
            mastery = TopicMastery(student_id=student_id, topic_id=topic_id, mastery_level=0.0)
            self.session.add(mastery)
            await self.session.commit()
            await self.session.refresh(mastery)

        mastery_level_value = mastery.mastery_level
        difficulty = mastery_to_difficulty(mastery_level_value)

        # 2. Получаем краткосрочную историю (последние 4 попытки)
        attempts_stmt = select(Attempt).where(
            Attempt.student_id == student_id,
            Attempt.topic_id == topic_id
        ).order_by(Attempt.completed_at.desc()).limit(4)

        attempts_result = await self.session.exec(attempts_stmt)
        recent_attempts = attempts_result.all()

        # 3. Собираем КОНТЕКСТ ТЬЮТОРА (структурированно!)
        context_parts = []

        # 🔹 Долгосрочные данные
        if mastery.identified_weaknesses:
            context_parts.append(f" СЛАБЫЕ МЕСТА: {', '.join(mastery.identified_weaknesses)}. "
                                 f"Сделай акцент на их проработке, но НЕ упоминай ошибки в тексте задания.")

        if mastery.practice_streak >= 3:
            context_parts.append(f" МОТИВАЦИЯ: Студент практикуется {mastery.practice_streak} дней подряд. "
                                 f"Поддержи ритм, чуть усложни задачу.")

        # 🔹 Краткосрочные данные (последние попытки)
        if recent_attempts:
            context_parts.append("📜 ПОСЛЕДНИЕ ПОПЫТКИ:")
            for i, att in enumerate(recent_attempts, 1):
                status = "✅ Верно" if att.is_correct else f"❌ Ошибка: {att.weakness or 'неизвестно'}"
                context_parts.append(f"  {i}. {status}")

        tutor_context = "\n".join(context_parts) if context_parts else "🆕 НОВЫЙ СТУДЕНТ. Начни с базы."

        # 4. История заданий (чтобы не повторяться)
        history_stmt = select(GeneratedTask).where(
            GeneratedTask.student_id == student_id,
            GeneratedTask.topic_id == topic_id
        ).order_by(GeneratedTask.created_at.desc()).limit(3)

        history_tasks = (await self.session.exec(history_stmt)).all()
        history_block = ""
        if history_tasks:
            history_block = "📚 РАНЕЕ ДАВАЛИСЬ:\n" + "\n".join(
                f"{i}. {json.loads(t.content_json).get('question', '')}"
                for i, t in enumerate(history_tasks, 1)
            )

        # Экранируем для .format()
        ctx_escaped = tutor_context.replace("{", "{{").replace("}", "}}")
        hist_escaped = history_block.replace("{", "{{").replace("}", "}}")

        # 5. Формируем промпт
        prompt = TASK_PROMPT.format(
            topic=topic_name,
            difficulty=mastery_to_difficulty(mastery.mastery_level),
            tutor_context_block=ctx_escaped,
            history_block=hist_escaped
        )

        # 5. Вызываем LLM
        config = LLMConfig(temperature=0.6, max_tokens=1024)
        task_output = await self.llm.generate_task(prompt, config)

        # 6. Сохраняем задание
        generated = GeneratedTask(
            student_id=student_id,
            topic_id=topic_id,
            difficulty=difficulty,
            content_json=json.dumps(task_output.model_dump()),
            created_at=datetime.utcnow()
        )
        self.session.add(generated)
        await self.session.commit()
        await self.session.refresh(generated)

        # 7. Возвращаем результат
        return {
            "task_id": generated.id,
            "question": task_output.question,
            "expected_answer": task_output.expected_answer,
            "answer_type": task_output.answer_type,
            "difficulty": difficulty,
            "mastery_level": round(mastery_level_value, 2),
            "explanation": task_output.explanation
        }

    async def submit_answer(self, student_id: int, topic_id: int, task_id: int, is_correct: bool) -> dict:
        # Обновляем mastery по формуле +0.2 / -0.1
        new_mastery = await update_mastery(self.session, student_id, topic_id, is_correct)

        return {
            "is_correct": is_correct,
            "new_mastery_level": round(new_mastery, 2),
            "next_difficulty": mastery_to_difficulty(new_mastery)
        }

    @staticmethod
    def is_valid_python_syntax(code: str) -> bool:
        """Проверяет синтаксис кода через Python AST"""
        try:
            # Пустой код считаем валидным (студент ещё не начал писать)
            if not code.strip():
                return True
            ast.parse(code)
            return True
        except SyntaxError:
            return False

    @staticmethod
    def is_meaningful_code(code: str) -> bool:
        """
        Проверяет, что код содержит ОСМЫСЛЕННЫЕ конструкции,
        а не просто число/строку/комментарий.
        """
        if not code.strip():
            return False

        # 🔹 Отбрасываем явный "не-код"
        stripped = code.strip()
        if stripped.isdigit():  # Просто цифры: 12345
            return False
        if stripped.replace('.', '').isdigit():  # Дробные числа: 3.14
            return False
        if stripped.startswith('"') or stripped.startswith("'"):  # Просто строка: "hello"
            return False
        if stripped.startswith('#'):  # Просто комментарий
            return False

        # 🔹 Проверяем через AST: есть ли вызовы функций, присваивания, условия?
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                # Ищем осмысленные конструкции
                if isinstance(node, (ast.Call, ast.Assign, ast.If, ast.For, ast.While, ast.FunctionDef, ast.Import)):
                    return True
            # Если ничего не нашли — код "пустой" по смыслу
            return False
        except:
            return False

    async def verify_student_answer(self, question: str, expected_answer: str, student_answer: str) -> dict:
        # 1. Проверяем синтаксис
        if not self.is_valid_python_syntax(student_answer):
            return {
                "is_correct": False,
                "explanation": "❌ Синтаксическая ошибка. Проверьте скобки, отступы, двоеточия.",
                "weakness": "syntax_error"
            }

        # 🔹 2. Проверяем, что это ОСМЫСЛЕННЫЙ код
        if not self.is_meaningful_code(student_answer):
            return {
                "is_correct": False,
                "explanation": "⚠️ Это не программа. Напишите код с использованием функций (input, print) и логики (if, переменные).",
                "weakness": "not_code"
            }

        # 3. Отправляем LLM для проверки логики
        prompt = VERIFY_PROMPT.format(
            question=question,
            expected_answer=expected_answer,
            student_answer=student_answer
        )

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "qwen2.5:3b",
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1, "num_predict": 512}
                }
            )
            response.raise_for_status()
            data = response.json()

            # 🔹 ОТЛАДКА: печатаем сырой ответ
            print(f"📡 Сырой ответ LLM: {data.get('response')[:200]}...")

            try:
                llm_json = json.loads(data["response"])

                # 🔹 Гарантируем weakness (если null или отсутствует → 'none')
                weakness = llm_json.get("weakness")
                if weakness is None or weakness == "":
                    weakness = "none"

                print(f"✅ is_correct: {llm_json.get('is_correct')}")
                print(f"💬 weakness: {weakness}")

                return {
                    "is_correct": llm_json.get("is_correct", False),
                    "explanation": llm_json.get("explanation", "Объяснение не предоставлено"),
                    "weakness": weakness  # ← Теперь точно не None
                }
            except (json.JSONDecodeError, KeyError) as e:
                print(f"⚠️ Ошибка парсинга: {e}")
                return {
                    "is_correct": False,
                    "explanation": "Ошибка проверки",
                    "weakness": "parse_error"
                }


    async def generate_detailed_explanation(
        self,
        question: str,
        expected_answer: str,
        student_id: int,
        topic_id: int
    ) -> dict:
        """
        Генерирует подробное пошаговое объяснение решения
        """
        prompt = f"""Ты — терпеливый репетитор по Python. Объясни решение задачи ПОДРОБНО и ПОШАГОВО.
    
    ЗАДАНИЕ:
    {question}
    
    ПРАВИЛЬНЫЙ ОТВЕТ:
    {expected_answer}
    
    ИНСТРУКЦИИ:
    1. Объясни, ЧТО нужно сделать в задаче (простыми словами)
    2. Разбери решение ПОШАГОВО (каждая строка кода)
    3. Объясни, ПОЧЕМУ это работает (концепции Python)
    4. Дай 2-3 ПОДСКАЗКИ на будущее
    5. Укажи на ТИПИЧНЫЕ ОШИБКИ
    
    Отвечай СТРОГО в формате JSON:
    {{
      "main_explanation": "Общее объяснение задачи (2-3 предложения)",
      "steps": [
        "Шаг 1: ...",
        "Шаг 2: ...",
        "Шаг 3: ..."
      ],
      "hints": [
        "Подсказка 1",
        "Подсказка 2"
      ]
    }}
    
    Будь максимально понятным и дружелюбным. Используй примеры."""

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "qwen2.5:7b",
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.3, "num_predict": 1024}
                }
            )
            response.raise_for_status()
            data = response.json()

            try:
                explanation = json.loads(data["response"])
                return {
                    "main_explanation": explanation.get("main_explanation", "Объяснение недоступно"),
                    "steps": explanation.get("steps", []),
                    "hints": explanation.get("hints", [])
                }
            except (json.JSONDecodeError, KeyError) as e:
                print(f"⚠️ Ошибка парсинга объяснения: {e}")
                return {
                    "main_explanation": data.get("response", "Не удалось сгенерировать объяснение"),
                    "steps": [],
                    "hints": []
                }