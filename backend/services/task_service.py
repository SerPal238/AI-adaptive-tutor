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
from pathlib import Path
SYLLABUS_PATH = Path(__file__).parent.parent / "topic_syllabus.json"

try:
    with open(SYLLABUS_PATH, "r", encoding="utf-8") as f:
        TOPIC_SYLLABUS = json.load(f)
    print(f"✅ Syllabus загружен: {len(TOPIC_SYLLABUS)} тем")
except FileNotFoundError:
    print(f"⚠️ Файл syllabus не найден: {SYLLABUS_PATH}")
    TOPIC_SYLLABUS = {}

TASK_PROMPT = """Ты — персональный репетитор по Python. Сгенерируй УЧЕБНОЕ ЗАДАНИЕ, строго соответствующее текущему этапу изучения темы.

 КОНТЕКСТ:
Тема: {topic}
Описание: {topic_description}
Текущий этап: {stage_name}
Фокус этапа: {stage_focus}

 СТРОГИЕ ПРАВИЛА:
1. РАЗРЕШЕНО использовать ТОЛЬКО: {allowed_constructs}
2. ЗАПРЕЩЕНО использовать: {banned_constructs}
3. Задание должно быть КРАТКИМ (1-3 предложения). Тренируй ТОЛЬКО фокус этапа.
4. НЕ усложняй задание. Если этап "basic_print", давай задания только на print().
5. НЕ повторяй задания из истории.
6. expected_answer должен быть РАБОЧИМ, лаконичным кодом.
7. explanation — краткая подсказка (1 предложение), а не решение.

 КОНТЕКСТ ТЬЮТОРА (учти, но НЕ упоминай в тексте задания):
{tutor_context_block}

 ИСТОРИЯ (НЕ ПОВТОРЯЙ):
{history_block}

 ОТВЕТЬ СТРОГО В ФОРМАТЕ JSON (без markdown, без лишних слов):
{{
  "question": "Текст задания",
  "expected_answer": "Корректный Python-код",
  "answer_type": "code",
  "explanation": "Краткое пояснение концепции"
}}"""

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


# 🔹 Функция выбора этапа (ВНЕ класса, с НУЛЕВЫМ отступом!)
def get_current_stage(topic_name: str, mastery_level: float) -> dict:
    """Возвращает текущий этап обучения"""
    syllabus = TOPIC_SYLLABUS.get(topic_name, {})
    stages = syllabus.get("stages", [])

    for stage in stages:
        min_m, max_m = stage["mastery_range"]
        if min_m <= mastery_level < max_m:
            return stage

    return stages[-1] if stages else {
        "name": "general",
        "focus": "практика",
        "allowed": [],
        "banned": []
    }

class TaskGenerationService:
    def __init__(self, llm: LLMProvider, session: AsyncSession):
        self.llm = llm
        self.session = session

    async def generate_adaptive_task(self, student_id: int, topic_id: int, topic_name: str) -> dict:
        # 1. Получаем/создаём запись mastery
        stmt = select(TopicMastery).where(
            TopicMastery.student_id == student_id,
            TopicMastery.topic_id == topic_id
        )
        result = await self.session.exec(stmt)
        mastery = result.first()

        if not mastery:
            mastery = TopicMastery(student_id=student_id, topic_id=topic_id, mastery_level=0.0)
            self.session.add(mastery)
            await self.session.commit()
            await self.session.refresh(mastery)

        mastery_level = mastery.mastery_level

        # 🔹 ОПРЕДЕЛЯЕМ ТЕКУЩИЙ ЭТАП ПО SYLLABUS
        stage = get_current_stage(topic_name, mastery_level)
        stage_name = stage["name"]
        stage_focus = stage["focus"]
        allowed = stage.get("allowed", [])
        banned = stage.get("banned", [])
        topic_desc = TOPIC_SYLLABUS.get(topic_name, {}).get("description", "Базовые концепции Python")

        # Для UI/БД оставляем difficulty, вычисляя его из индекса этапа
        stages_list = TOPIC_SYLLABUS.get(topic_name, {}).get("stages", [])
        stage_index = next((i for i, s in enumerate(stages_list) if s["name"] == stage_name), 0)
        difficulty = "easy" if stage_index < 2 else "medium" if stage_index == 2 else "hard"

        # 2. Краткосрочная история (последние 3 попытки)
        attempts_stmt = select(Attempt).where(
            Attempt.student_id == student_id,
            Attempt.topic_id == topic_id
        ).order_by(Attempt.completed_at.desc()).limit(3)
        recent_attempts = (await self.session.exec(attempts_stmt)).all()

        # 3. Контекст тьютора
        context_parts = []
        if mastery.identified_weaknesses:
            context_parts.append(f"⚠️ СЛАБЫЕ МЕСТА: {', '.join(mastery.identified_weaknesses)}. "
                                 f"Акцентируй внимание на этом в объяснении, но НЕ в тексте задания.")
        if mastery.practice_streak >= 3:
            context_parts.append(f"🔥 МОТИВАЦИЯ: Практика {mastery.practice_streak} дней подряд. Поддержи ритм.")
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
            history_block = " РАНЕЕ ДАВАЛИСЬ:\n" + "\n".join(
                f"{i}. {json.loads(t.content_json).get('question', '')}"
                for i, t in enumerate(history_tasks, 1)
            )

        # Экранирование фигурных скобок для .format()
        ctx_escaped = tutor_context.replace("{", "{{").replace("}", "}}")
        hist_escaped = history_block.replace("{", "{{").replace("}", "}}")

        # 5. Формируем промпт
        prompt = TASK_PROMPT.format(
            topic=topic_name,
            topic_description=topic_desc,
            stage_name=stage_name,
            stage_focus=stage_focus,
            allowed_constructs=", ".join(allowed),
            banned_constructs=", ".join(banned),
            tutor_context_block=ctx_escaped,
            history_block=hist_escaped
        )

        # 6. Вызываем LLM
        config = LLMConfig(temperature=0.5, max_tokens=800)
        try:
            task_output = await self.llm.generate_task(prompt, config)
            # Безопасное извлечение данных (поддержка и Pydantic, и dict)
            task_data = task_output.model_dump() if hasattr(task_output, "model_dump") else task_output
        except Exception as e:
            print(f"❌ Ошибка генерации задания: {e}")
            raise

        # 7. Сохраняем задание
        generated = GeneratedTask(
            student_id=student_id,
            topic_id=topic_id,
            difficulty=difficulty,
            content_json=json.dumps(task_data),
            created_at=datetime.utcnow()
        )
        self.session.add(generated)
        await self.session.commit()
        await self.session.refresh(generated)

        # 8. Возвращаем результат
        return {
            "task_id": generated.id,
            "question": task_data.get("question", ""),
            "expected_answer": task_data.get("expected_answer", ""),
            "answer_type": task_data.get("answer_type", "code"),
            "difficulty": difficulty,
            "mastery_level": round(mastery_level, 2),
            "explanation": task_data.get("explanation", ""),
            "stage_name": stage_name
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