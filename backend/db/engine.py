# backend/db/engine.py
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = "sqlite+aiosqlite:///./students.db"

# Создаём асинхронный движок
engine = create_async_engine(DATABASE_URL, echo=False)

async def get_session():
    """
    Dependency для FastAPI: создаёт сессию БД и гарантирует её закрытие.
    """
    async with AsyncSession(engine) as session:
        yield session