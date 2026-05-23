from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from services.task_service import TaskGenerationService
from sqlmodel import select
from db.models import GeneratedTask
import json
# 🔹 Импорт из нашей новой архитектуры
from db.engine import engine, get_session
from db.models import SQLModel
from services.student_service import (
    get_or_create_student,
    analyze_answer,
    update_gamification,
    generate_content,
    verify_access,
    get_student_full_status
)
from llm.ollama_client import OllamaClient
from knowledge_graph import graph_manager  # твой граф (остаётся синхронным)

# ─────────────────────────────────────────────────────────────
# 🔹 Инициализация БД при старте сервера
# ─────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Создаём таблицы, если их нет
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    # Загружаем граф знаний из БД в память
    async with AsyncSession(engine) as session:
        await graph_manager.load_from_db(session)

    yield  # Сервер запущен


app = FastAPI(title="AI Adaptive Tutor API", version="1.0", lifespan=lifespan)

# 🔹 Разрешаем запросы с фронтенда (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # На проде замени на ["http://localhost:3000", "https://твой-домен"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────
# 🔹 Модели запросов (изменили str → int для совместимости с БД)
# ─────────────────────────────────────────────────────────────
class AnswerRequest(BaseModel):
    student_id: int
    topic_id: int
    task_id: int
    is_correct: bool = False  # ← для обратной совместимости
    student_answer: str = ""   # ← новое поле: текст ответа студента

class ContentRequest(BaseModel):
    student_id: int
    topic_id: int

class StudentInitRequest(BaseModel):
    name: str = "Студент"
# ─────────────────────────────────────────────────────────────
# 🔹 1. GET /student/{id} — статус студента + карта знаний
# ─────────────────────────────────────────────────────────────
@app.get("/student/{student_id}")
async def get_status(student_id: int, session: AsyncSession = Depends(get_session)):
    # Авто-создание студента, если нет в БД
    await get_or_create_student(session, student_id)

    # Получаем полный статус через сервис
    status = await get_student_full_status(session, student_id)
    if not status:
        raise HTTPException(status_code=404, detail="Student not found")

    # 🔹 ДОБАВЬ: Возвращаем граф знаний
    return {
        **status,
        "knowledge_graph_nodes": list(graph_manager.graph.nodes(data=True))
    }


# ─────────────────────────────────────────────────────────────
# 🔹 2. POST /task/generate — генерация адаптивного задания
# ─────────────────────────────────────────────────────────────
@app.post("/task/generate")
async def get_task(req: ContentRequest, session: AsyncSession = Depends(get_session)):
    # Проверяем доступ через граф
    access = await verify_access(session, req.student_id, req.topic_id)
    if not access["access"]:
        return {"error": access["reason"], "access": False}

    # Генерируем задание через LLM-сервис
    llm = OllamaClient()
    try:
        task = await generate_content(session, req.student_id, req.topic_id, llm)
        return {**task, "access": True}
    except Exception as e:
        # 🔹 ПОДРОБНЫЙ ЛОГ ОШИБКИ
        import traceback
        print(f"🔴 LLM Error Details:")
        print(f"  Type: {type(e).__name__}")
        print(f"  Message: {str(e)}")
        print(f"  Traceback: {traceback.format_exc()}")

        raise HTTPException(status_code=500, detail=f"Failed to generate task: {str(e)}")


# ─────────────────────────────────────────────────────────────
# 🔹 3. POST /task/submit — обработка ответа студента
# ─────────────────────────────────────────────────────────────
@app.post("/task/submit")
async def submit_answer(req: AnswerRequest, session: AsyncSession = Depends(get_session)):
    print(f" Получен ответ: student_id={req.student_id}, task_id={req.task_id}")

    if req.student_answer and len(req.student_answer.strip()) > 0:
        print("🤖 Запускаю LLM-верификацию...")

        from services.task_service import TaskGenerationService
        from llm.ollama_client import OllamaClient
        from sqlmodel import select
        from db.models import GeneratedTask
        import json

        stmt = select(GeneratedTask).where(GeneratedTask.id == req.task_id)
        result = await session.exec(stmt)
        task = result.first()

        if task:
            task_data = json.loads(task.content_json)

            llm = OllamaClient()
            service = TaskGenerationService(llm, session)

            # 🔹 Получаем вердикт LLM
            llm_feedback = await service.verify_student_answer(
                question=task_data.get("question", ""),
                expected_answer=task_data.get("expected_answer", ""),
                student_answer=req.student_answer
            )

            print(f"✅ Вердикт LLM: is_correct={llm_feedback.get('is_correct')}")
            print(f"💬 Weakness: {llm_feedback.get('weakness')}")

            is_correct = llm_feedback.get("is_correct", False)

            #  Передаём llm_feedback
            from services.student_service import analyze_answer, update_gamification
            analysis = await analyze_answer(
                session,
                req.student_id,
                req.topic_id,
                is_correct,
                llm_feedback=llm_feedback
            )
            game_update = await update_gamification(session, req.student_id, is_correct)

            return {
                "is_correct": is_correct,
                "explanation": llm_feedback.get("explanation", ""),
                "weakness": llm_feedback.get("weakness"),
                "analysis": analysis,
                "gamification": game_update
            }

    # Фолбэк (старая логика)
    print("🔄 Использую старую логику проверки")
    from services.student_service import analyze_answer, update_gamification
    analysis = await analyze_answer(session, req.student_id, req.topic_id, req.is_correct)
    game_update = await update_gamification(session, req.student_id, req.is_correct)

    return {
        "is_correct": req.is_correct,
        "analysis": analysis,
        "gamification": game_update
    }

# ─────────────────────────────────────────────────────────────
# эндпоинт для инициализации тестового студента
# ─────────────────────────────────────────────────────────────
@app.post("/student/{student_id}/init")
async def init_student(
    student_id: int,
    request: StudentInitRequest,  # ← Принимаем JSON body
    session: AsyncSession = Depends(get_session)
):
    student = await get_or_create_student(session, student_id, request.name)
    return {"message": f"Student {request.name} initialized", "id": student_id}

@app.get("/students")
async def get_all_students(session: AsyncSession = Depends(get_session)):
    """
    Получить список всех студентов
    """
    from sqlmodel import select
    from db.models import Student

    stmt = select(Student).order_by(Student.id)
    result = await session.exec(stmt)
    students = result.all()

    return [
        {
            "id": s.id,
            "name": s.name,
            "xp": s.xp,
            "level": s.level
        }
        for s in students
    ]


@app.post("/task/explain")
async def explain_task(req: AnswerRequest, session: AsyncSession = Depends(get_session)):
    """
    Сгенерировать подробное объяснение задания (без проверки ответа)
    """
    print(f"💡 Запрос объяснения: student_id={req.student_id}, task_id={req.task_id}")

    # Получаем задание
    stmt = select(GeneratedTask).where(GeneratedTask.id == req.task_id)
    result = await session.exec(stmt)
    task = result.first()

    if not task:
        raise HTTPException(status_code=404, detail="Задание не найдено")

    task_data = json.loads(task.content_json)

    # Создаём сервис
    llm = OllamaClient()
    service = TaskGenerationService(llm, session)

    # 🔹 Генерируем подробное объяснение
    explanation = await service.generate_detailed_explanation(
        question=task_data.get("question", ""),
        expected_answer=task_data.get("expected_answer", ""),
        student_id=req.student_id,
        topic_id=req.topic_id
    )

    # 🔹 Снижаем mastery (наказание за пропуск)
    from services.adaptation import update_mastery
    new_mastery = await update_mastery(session, req.student_id, req.topic_id, is_correct=False)

    print(f"✅ Объяснение сгенерировано. Новый mastery: {new_mastery}")

    return {
        "detailed_explanation": explanation.get("main_explanation", ""),
        "step_by_step": explanation.get("steps", []),
        "hints": explanation.get("hints", []),
        "new_mastery": new_mastery
    }