from knowledge_graph import graph_manager

# --- Имитация Базы Данных студента ---
STUDENT_DB = {
    "student_1": {
        "name": "Иван",
        "xp": 0,
        "level": 1,
        "mastered_topics": ["intro"],  # Уже знает введение
        "mastery_scores": {"intro": 1.0}  # mastery: 0.0 - 1.0
    }
} 


def get_student(student_id):
    return STUDENT_DB.get(student_id)


# --- МОДУЛЬ 1: АНАЛИЗАТОР (Analyzer) ---
# Анализирует ответ студента
def analyze_answer(student_id, topic_id, is_correct):
    student = get_student(student_id)
    if not student: return {"error": "Student not found"}

    current_mastery = student["mastery_scores"].get(topic_id, 0.0)

    # Логика адаптации: если правильно -> mastery растет, если нет -> падает или стоит
    if is_correct:
        delta = 0.2  # +20% к знанию темы
    else:
        delta = -0.1  # Штраф за ошибку

    new_mastery = max(0.0, min(1.0, current_mastery + delta))
    student["mastery_scores"][topic_id] = new_mastery

    # Если mastery > 0.9, считаем тему изученной
    if new_mastery >= 0.9 and topic_id not in student["mastered_topics"]:
        student["mastered_topics"].append(topic_id)
        return {"status": "completed", "new_mastery": new_mastery, "unlocked": True}

    return {"status": "in_progress", "new_mastery": new_mastery, "unlocked": False}


# --- МОДУЛЬ 2: ИГРОВОЙ ДВИЖОК (Game Engine) ---
# Начисляет XP и уровни
def update_gamification(student_id, is_correct):
    student = get_student(student_id)
    xp_gain = 25 if is_correct else 5

    student["xp"] += xp_gain

    # Простая формула уровня: каждые 100 XP = 1 уровень
    old_level = student["level"]
    student["level"] = 1 + (student["xp"] // 100)

    level_up = student["level"] > old_level
    return {"xp": student["xp"], "level": student["level"], "level_up": level_up}


# --- МОДУЛЬ 3: ГЕНЕРАТОР (Generator) ---
# Подбирает контент на основе уровня mastery
def generate_content(topic_id, mastery_level):
    # В реальном проекте здесь будет вызов к LLM API
    # Сейчас мы имитируем адаптацию сложности
    if mastery_level < 0.4:
        difficulty = "easy"
        content = f"Простое объяснение темы '{topic_id}' с базовыми примерами."
    elif mastery_level < 0.8:
        difficulty = "medium"
        content = f"Стандартная задача по теме '{topic_id}'."
    else:
        difficulty = "hard"
        content = f"Сложная олимпиадная задача по теме '{topic_id}'."

    return {"difficulty": difficulty, "content": content}


# --- МОДУЛЬ 4: ПРОВЕРЯЛЬЩИК (Verifier) ---
# Проверяет логику графа (можно ли учить эту тему?)
def verify_access(student_id, topic_id):
    student = get_student(student_id)
    mastered = student["mastered_topics"]

    # Используем граф для проверки
    unlocked_topics = graph_manager.get_unlocked_topics(mastered)

    if topic_id in unlocked_topics:
        return {"access": True, "reason": "Prerequisites are completed"}
    else:
        prereqs = graph_manager.get_prerequisites(topic_id)
        missing = [p for p in prereqs if p not in mastered]
        return {"access": False, "reason": f"Need to finish: {missing}"}
