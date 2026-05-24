# backend/db/engine.py
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from pathlib import Path
DB_PATH = Path(__file__).parent.parent / "students.db"
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

# Создаём асинхронный движок
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,  # Проверка соединений перед использованием
)

async def get_session():
    """
    Dependency для FastAPI: создаёт сессию БД и гарантирует её закрытие.
    """
    async with AsyncSession(engine) as session:
        yield session