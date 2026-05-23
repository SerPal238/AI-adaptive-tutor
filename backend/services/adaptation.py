"""
Модуль с формулами адаптивной сложности.
Вынесен отдельно, чтобы легко менять пороги и логику в одном месте.
"""
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from db.models import TopicMastery
from datetime import datetime
# ─────────────────────────────────────────────────────────────
# 🔹 Пороги сложности (твои значения)
# ─────────────────────────────────────────────────────────────
DIFFICULTY_THRESHOLDS = {
    "easy": 0.4,  # mastery < 0.4 → easy
    "medium": 0.8,  # 0.4 ≤ mastery < 0.8 → medium
    "hard": 1.0  # mastery ≥ 0.8 → hard
}


def mastery_to_difficulty(level: float) -> str:
    if level < DIFFICULTY_THRESHOLDS["easy"]:
        return "easy"
    elif level < DIFFICULTY_THRESHOLDS["medium"]:
        return "medium"
    else:
        return "hard"


# 🔹 НОВАЯ: Получить или создать mastery
async def get_or_create_mastery(session: AsyncSession, student_id: int, topic_id: int) -> TopicMastery:
    stmt = select(TopicMastery).where(
        TopicMastery.student_id == student_id,
        TopicMastery.topic_id == topic_id
    )
    result = await session.exec(stmt)
    mastery = result.first()

    if not mastery:
        mastery = TopicMastery(student_id=student_id, topic_id=topic_id, mastery_level=0.0)
        session.add(mastery)
        await session.commit()
        await session.refresh(mastery)

    return mastery


# 🔹 НОВАЯ: Обновить mastery
async def update_mastery(session: AsyncSession, student_id: int, topic_id: int, is_correct: bool) -> float:
    mastery = await get_or_create_mastery(session, student_id, topic_id)

    if is_correct:
        mastery.mastery_level += 0.2
    else:
        mastery.mastery_level -= 0.1

    mastery.mastery_level = max(0.0, min(1.0, mastery.mastery_level))
    mastery.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(mastery)
    return mastery.mastery_level


def calculate_mastery_delta(is_correct: bool) -> float:
    """
    Возвращает дельту для обновления mastery по формуле.

    Args:
        is_correct: правильно ли ответил студент

    Returns:
        +0.2 за правильный ответ, -0.1 за ошибку
    """
    return 0.2 if is_correct else -0.1


def clamp_mastery(value: float) -> float:
    """
    Ограничивает значение mastery диапазоном [0.0, 1.0].

    Args:
        value: новое значение мастерства

    Returns:
        значение в допустимом диапазоне
    """
    return max(0.0, min(1.0, value))


def is_topic_mastered(mastery_level: float, threshold: float = 0.9) -> bool:
    """
    Проверяет, считается ли тема изученной.

    Args:
        mastery_level: текущий уровень мастерства
        threshold: порог для считания темы "изученной" (по умолчанию 0.9)

    Returns:
        True, если mastery_level >= threshold
    """
    return mastery_level >= threshold