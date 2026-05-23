# backend/db/models.py
from sqlmodel import SQLModel, Field, Relationship, Column, JSON
from typing import List, Optional
from datetime import datetime


# ─────────────────────────────────────────────────────────────
# 🔹 Student — студенты
# ─────────────────────────────────────────────────────────────
class Student(SQLModel, table=True):
    __tablename__ = "student"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    xp: int = Field(default=0)
    level: int = Field(default=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Обратные связи
    mastery_levels: List["TopicMastery"] = Relationship(
        back_populates="student",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    attempts: List["Attempt"] = Relationship(
        back_populates="student",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

    learning_style: Optional[str] = Field(default="balanced", description="visual|auditory|kinesthetic|balanced")
    hint_preference: Optional[str] = Field(default="socratic", description="direct|socratic|minimal")
    motivation_notes: Optional[str] = Field(default=None, description="Заметки репетитора о студенте")
    last_session_summary: Optional[str] = Field(default=None, description="Краткий итог прошлого занятия")

# ─────────────────────────────────────────────────────────────
# 🔹 Topic — темы/предметы
# ─────────────────────────────────────────────────────────────
class Topic(SQLModel, table=True):
    __tablename__ = "topic"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    subject: str
    prerequisites: str = Field(default="", description="Список ID предков через запятую: '1,3,5'")

    # Обратная связь (опционально)
    mastery_records: List["TopicMastery"] = Relationship(back_populates="topic")


# ─────────────────────────────────────────────────────────────
# 🔹 TopicMastery — уровень владения темой (студент + тема)
# ─────────────────────────────────────────────────────────────
class TopicMastery(SQLModel, table=True):
    __tablename__ = "topic_mastery"

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="student.id", index=True)
    topic_id: int = Field(foreign_key="topic.id", index=True)

    # базовая метрика (для UI и фолбэка)
    mastery_level: float = Field(default=0.0, ge=0.0, le=1.0)

    # ДЕТАЛИЗАЦИЯ навыков (для адаптации)
    # Пример: {"syntax": 0.8, "logic": 0.4, "debugging": 0.2}
    skill_breakdown: Optional[dict] = Field(default=None, sa_column=Column(JSON))

    # КАЧЕСТВЕННЫЕ инсайты (для персонализации)
    # Пример: ["forgets_colon", "confuses_input_print", "off_by_one"]
    identified_weaknesses: List[str] = Field(default_factory=list, sa_column=Column(JSON))

    # ПРЕДПОЧТЕНИЯ студента (по этой теме)
    # Пример: "example" | "question" | "direct"
    preferred_hint_style: Optional[str] = Field(default=None)

    # ВРЕМЕННЫЕ метрики
    last_practiced: Optional[datetime] = Field(default=None)
    practice_streak: int = Field(default=0)  # Дней практики подряд

    correct_streak: int = Field(default=0, description="Сколько раз подряд ответил верно")

    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # связи
    student: Student = Relationship(back_populates="mastery_levels")
    topic: Topic = Relationship(back_populates="mastery_records")


# ─────────────────────────────────────────────────────────────
# 🔹 GeneratedTask — сгенерированные задания (кэш от LLM)
# ─────────────────────────────────────────────────────────────
class GeneratedTask(SQLModel, table=True):
    __tablename__ = "generated_task"

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="student.id", index=True)
    topic_id: int = Field(foreign_key="topic.id", index=True)
    difficulty: str = Field(default="medium")  # easy/medium/hard
    content_json: str  # JSON с вопросом, вариантами, ответом
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─────────────────────────────────────────────────────────────
# 🔹 Attempt — журнал попыток ответа (история)
# ─────────────────────────────────────────────────────────────
class Attempt(SQLModel, table=True):
    __tablename__ = "attempt"

    id: Optional[int] = Field(default=None, primary_key=True)
    student_id: int = Field(foreign_key="student.id", index=True)
    topic_id: int = Field(foreign_key="topic.id", index=True)
    task_id: Optional[int] = Field(default=None, foreign_key="generated_task.id")
    is_correct: bool
    score: float = Field(default=0.0)
    completed_at: datetime = Field(default_factory=datetime.utcnow)

    # 🔹 НОВОЕ: Диагноз от LLM для конкретной попытки
    weakness: Optional[str] = Field(default=None, description="Слабое место: syntax_error, logic_flow, input_syntax и т.д.")

    # Обратные связи
    student: Student = Relationship(back_populates="attempts")