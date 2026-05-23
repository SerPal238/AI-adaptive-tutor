from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from db.models import Student, TopicMastery, Attempt, Topic
from services.adaptation import mastery_to_difficulty, DIFFICULTY_THRESHOLDS
from knowledge_graph import graph_manager
from datetime import datetime
import json


# ─────────────────────────────────────────────────────────────
# 🔹 get_student → async
# ─────────────────────────────────────────────────────────────
async def get_student(session: AsyncSession, student_id: int) -> Student | None:
    stmt = select(Student).where(Student.id == student_id)
    result = await session.exec(stmt)
    return result.first()


async def get_or_create_student(session: AsyncSession, student_id: int, name: str = "Student") -> Student:
    student = await get_student(session, student_id)
    if not student:
        student = Student(id=student_id, name=name, xp=0, level=1)
        session.add(student)
        await session.commit()
        await session.refresh(student)
    return student


# ─────────────────────────────────────────────────────────────
# 🔹 analyze_answer → async (логика +0.2 / -0.1)
# ─────────────────────────────────────────────────────────────
async def analyze_answer(
        session: AsyncSession,
        student_id: int,
        topic_id: int,
        is_correct: bool,
        llm_feedback: dict | None = None
) -> dict:
    student = await get_student(session, student_id)
    if not student:
        return {"error": "Student not found"}

    # Получаем или создаём mastery
    stmt = select(TopicMastery).where(
        TopicMastery.student_id == student_id,
        TopicMastery.topic_id == topic_id
    )
    result = await session.exec(stmt)
    mastery_record = result.first()

    if not mastery_record:
        mastery_record = TopicMastery(student_id=student_id, topic_id=topic_id, mastery_level=0.0)
        session.add(mastery_record)

    current_mastery = mastery_record.mastery_level
    delta = 0.2 if is_correct else -0.1
    new_mastery = max(0.0, min(1.0, current_mastery + delta))
    mastery_record.mastery_level = new_mastery

    # 🔹 1. Обновляем список слабых мест
    if llm_feedback:
        weakness = llm_feedback.get("weakness")

        # 🔹 Проверяем на None, "none", "None" (регистронезависимо)
        if weakness and str(weakness).lower().strip() != "none":
            current_weaknesses = mastery_record.identified_weaknesses or []
            if weakness not in current_weaknesses:
                current_weaknesses.append(weakness)
            mastery_record.identified_weaknesses = current_weaknesses
            print(f"💾 Сохранена слабость: {weakness}")
        else:
            print(f"ℹ️ Weakness = 'none', не сохраняем")

        if "preferred_hint_style" in llm_feedback:
            mastery_record.preferred_hint_style = llm_feedback["preferred_hint_style"]

    # 🔹 2. Обновляем время и стрик
    mastery_record.last_practiced = datetime.utcnow()
    mastery_record.practice_streak = (mastery_record.practice_streak or 0) + 1

    # 🔹 3. СОЗДАЁМ ЗАПИСЬ В ЖУРНАЛЕ ПОПЫТОК (Attempt)
    # Это нужно, чтобы хранить историю каждой проверки
    attempt = Attempt(
        student_id=student_id,
        topic_id=topic_id,
        is_correct=is_correct,
        # Сохраняем weakness из LLM, если есть
        weakness=llm_feedback.get("weakness") if llm_feedback else None,
        completed_at=datetime.utcnow()
    )
    session.add(attempt)

    # 🔹 Логика стрика правильных ответов
    if is_correct:
        mastery_record.correct_streak = (mastery_record.correct_streak or 0) + 1
    else:
        mastery_record.correct_streak = 0  # Сброс при ошибке

    # 🔹 Автоматическая очистка слабостей после 3 верных ответов подряд
    if mastery_record.correct_streak >= 3 and mastery_record.identified_weaknesses:
        print(f"🧹 Студент ответил верно 3 раза подряд. Слабости усвоены, очищаю профиль.")
        mastery_record.identified_weaknesses = []
        mastery_record.correct_streak = 0  # Сброс счётчика после очистки

    was_mastered = new_mastery >= 1.0
    unlocked_new = was_mastered and current_mastery < 1.0

    await session.commit()
    await session.refresh(mastery_record)

    return {
        "status": "completed" if was_mastered else "in_progress",
        "new_mastery_level": round(new_mastery, 2),
        "unlocked": unlocked_new,
        "difficulty_next": mastery_to_difficulty(new_mastery),
        "weaknesses": mastery_record.identified_weaknesses or [],
        "hint_style": mastery_record.preferred_hint_style,
        "streak": mastery_record.practice_streak
    }


# ─────────────────────────────────────────────────────────────
# 🔹 update_gamification → async (XP + уровни)
# ─────────────────────────────────────────────────────────────
async def update_gamification(session: AsyncSession, student_id: int, is_correct: bool) -> dict:
    student = await get_student(session, student_id)
    if not student:
        return {"error": "Student not found"}

    xp_gain = 25 if is_correct else 5
    student.xp += xp_gain

    old_level = student.level
    student.level = 1 + (student.xp // 100)
    level_up = student.level > old_level

    await session.commit()
    await session.refresh(student)

    return {
        "xp": student.xp,
        "level": student.level,
        "level_up": level_up,
        "xp_gain": xp_gain
    }


# ─────────────────────────────────────────────────────────────
# 🔹 generate_content → вызов LLM-сервиса
# ─────────────────────────────────────────────────────────────
async def generate_content(session: AsyncSession, student_id: int, topic_id: int, llm_provider) -> dict:
    from services.task_service import TaskGenerationService

    # Получаем название темы для промпта
    stmt = select(Topic).where(Topic.id == topic_id)
    topic = (await session.exec(stmt)).first()
    topic_name = topic.name if topic else f"Тема_{topic_id}"

    service = TaskGenerationService(llm_provider, session)
    return await service.generate_adaptive_task(student_id, topic_id, topic_name)


# ─────────────────────────────────────────────────────────────
# 🔹 verify_access → async (интеграция с графом)
# ─────────────────────────────────────────────────────────────
async def verify_access(session: AsyncSession, student_id: int, topic_id: int) -> dict:
    # Получаем все темы, где mastery >= 1.0 (изученные)
    stmt = select(TopicMastery.topic_id).where(
        TopicMastery.student_id == student_id,
        TopicMastery.mastery_level >= 1.0
    )
    result = await session.exec(stmt)
    mastered_ids = set(r for r in result.all())

    # Запрашиваем у графа доступные темы
    unlocked = graph_manager.get_unlocked_topics(mastered_ids)

    if topic_id in unlocked:
        return {"access": True, "reason": "Prerequisites are completed"}
    else:
        # Получаем недостающие предки
        prereqs = graph_manager.get_prerequisites(topic_id)  # должна быть в knowledge_graph
        missing = [p for p in prereqs if p not in mastered_ids]
        return {"access": False, "reason": f"Need to finish: {missing}"}


# ─────────────────────────────────────────────────────────────
# 🔹 Вспомогательная: получить полный статус студента
# ─────────────────────────────────────────────────────────────
async def get_student_full_status(session: AsyncSession, student_id: int) -> dict:
    student = await get_student(session, student_id)
    if not student:
        return None

    # Собираем mastery_scores по всем темам
    stmt = select(TopicMastery).where(TopicMastery.student_id == student_id)
    mastery_results = await session.exec(stmt)
    mastery_scores = {m.topic_id: round(m.mastery_level, 2) for m in mastery_results.all()}

    # Вычисляем изученные темы (mastery >= 1.0)
    mastered_topics = [tid for tid, score in mastery_scores.items() if score >= 1.0]

    # Получаем доступные через граф
    unlocked = graph_manager.get_unlocked_topics(set(mastered_topics))

    return {
        "student": {"id": student.id, "name": student.name, "xp": student.xp, "level": student.level},
        "mastery_scores": mastery_scores,
        "mastered_topics": mastered_topics,
        "unlocked_topics": unlocked
    }