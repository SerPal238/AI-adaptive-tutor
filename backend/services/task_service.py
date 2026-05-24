# backend/services/task_service.py
import ast
import json
import re
from sqlmodel import select
from datetime import datetime, timezone
from sqlmodel.ext.asyncio.session import AsyncSession
from db.models import GeneratedTask, TopicMastery, Attempt
from llm.base import LLMProvider, LLMConfig, TaskOutput
from services.adaptation import get_or_create_mastery, mastery_to_difficulty, update_mastery
from pathlib import Path
SYLLABUS_PATH = Path(__file__).parent.parent / "topic_syllabus.json"
import logging

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
TASK_PROMPT = (PROMPTS_DIR / "task_generation.txt").read_text(encoding="utf-8")
VERIFY_PROMPT = (PROMPTS_DIR / "verify_answer.txt").read_text(encoding="utf-8")
EXPLAIN_PROMPT = (PROMPTS_DIR / "detailed_explanation.txt").read_text(encoding="utf-8")

try:
    with open(SYLLABUS_PATH, "r", encoding="utf-8") as f:
        TOPIC_SYLLABUS = json.load(f)
    logger.info(f"✅ Syllabus загружен: {len(TOPIC_SYLLABUS)} тем")
except FileNotFoundError:
    logger.info(f"⚠️ Файл syllabus не найден: {SYLLABUS_PATH}")
    TOPIC_SYLLABUS = {}

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
        mastery = await get_or_create_mastery(self.session, student_id, topic_id)
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
            history_block = " РАНЕЕ ДАВАЛИСЬ:\n"
            for i, t in enumerate(history_tasks, 1):
                # t.content уже словарь (JSON-колонка), парсить не нужно
                question = t.content.get('question', '[вопрос недоступен]') if t.content else '[вопрос недоступен]'
                history_block += f"{i}. {question}\n"

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

            # 🔹 Защита от None
            if task_output is None:
                raise RuntimeError("LLM вернул None вместо TaskOutput")

            # Извлекаем данные (Pydantic модель → dict)
            task_data = task_output.model_dump()
        except Exception as e:
            logger.error(f"❌ Ошибка генерации задания: {e}")
            raise

        # 7. Сохраняем задание
        generated = GeneratedTask(
            student_id=student_id,
            topic_id=topic_id,
            difficulty=difficulty,
            content=task_data,
            created_at=datetime.now(timezone.utc)
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

    @staticmethod
    def _normalize_python_code(code: str) -> str:
        if not code or not code.strip():
            return code

        try:
            # Парсим и восстанавливаем код — это безопасно нормализует его
            tree = ast.parse(code)
            normalized = ast.unparse(tree)  # Python 3.9+
            return normalized
        except SyntaxError:
            # Если код битый — возвращаем как есть (ошибка поймается позже)
            return code

    @staticmethod
    def _extract_json(text: str) -> dict:
        """
        Извлекает валидный JSON из текста, который может содержать:
        - markdown-обёртки ```json ... ```
        - пояснения до/после JSON
        - лишние пробелы и символы
        """
        if not text:
            raise ValueError("Пустой ответ от LLM")

        # 1. Убираем markdown-обёртки ```json ... ```
        # Ищем блок между ``` и ```
        match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
        if match:
            json_str = match.group(1)
        else:
            # 2. Если нет обёрток — ищем первую { и последнюю }
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1 and end > start:
                json_str = text[start:end + 1]
            else:
                raise ValueError(f"Не удалось найти JSON в ответе: {text[:200]}")

        # 3. Парсим JSON
        return json.loads(json_str)

    async def verify_student_answer(self, question: str, expected_answer: str, student_answer: str, answer_type: str = "code") -> dict:
        # 🔹 0. НОРМАЛИЗУЕМ код студента (кавычки, пробелы, отступы)
        normalized_student_code = self._normalize_python_code(student_answer)

        # 1. Проверяем синтаксис нормализованного кода
        if not self.is_valid_python_syntax(normalized_student_code):
            return {
                "is_correct": False,
                "explanation": "❌ Синтаксическая ошибка. Проверьте скобки, отступы, двоеточия.",
                "weakness": "syntax_error"
            }

        # ✅ Проверяем осмысленность только для типа "code"
        if answer_type == "code" and not self.is_meaningful_code(normalized_student_code):
            return {
                "is_correct": False,
                "explanation": "⚠️ Это не программа. Напишите код с использованием функций.",
                "weakness": "not_code"
            }

        # 3. Отправляем LLM для проверки логики
        prompt = VERIFY_PROMPT.format(
            question=question,
            expected_answer=expected_answer,
            student_answer=normalized_student_code
        )
        config = LLMConfig(temperature=0.1, max_tokens=512)
        # 🔹 Вызываем LLM через единый клиент
        raw_response = await self.llm._call_ollama(prompt, config)
        logger.debug(f"📡 Сырой ответ LLM: {raw_response[:500]}...")

        try:
            llm_json = self._extract_json(raw_response)

            # Гарантируем нужные поля
            weakness = llm_json.get("weakness") or "none"
            if str(weakness).lower().strip() in ("none", "null", ""):
                weakness = "none"

            logger.info(f"✅ is_correct: {llm_json.get('is_correct')}")
            logger.info(f"💬 weakness: {weakness}")

            return {
                "is_correct": llm_json.get("is_correct", False),
                "explanation": llm_json.get("explanation", "Объяснение не предоставлено"),
                "weakness": weakness
            }
        except Exception as e:
            logger.warning(f"⚠️ Ошибка парсинга ответа LLM: {e}")
            logger.warning(f"Raw: {raw_response[:500]}")
            return {
                "is_correct": False,
                "explanation": f"Ошибка проверки ответа: {str(e)}",
                "weakness": "parse_error"
            }

    async def generate_detailed_explanation(self,
    question: str,
    expected_answer: str,
    student_id: int,
    topic_id: int
    ) -> dict:
        prompt = EXPLAIN_PROMPT.format(
            question=question,
            expected_answer=expected_answer
        )
        config = LLMConfig(temperature=0.3, max_tokens=1024)

        try:
            # 🔹 Вызываем LLM через единый клиент
            raw_response = await self.llm._call_ollama(prompt, config)
            logger.debug(f"📡 Сырой ответ LLM (explanation): {raw_response[:500]}...")

            explanation = self._extract_json(raw_response)
            return {
                "main_explanation": explanation.get("main_explanation", "Объяснение недоступно"),
                "steps": explanation.get("steps", []),
                "hints": explanation.get("hints", [])
            }
        except Exception as e:
            logger.warning(f"⚠️ Ошибка парсинга объяснения: {e}")
            logger.warning(f"Raw response: {raw_response[:500] if 'raw_response' in locals() else 'N/A'}")
            return {
                "main_explanation": "Не удалось сгенерировать объяснение",
                "steps": [],
                "hints": []
            }