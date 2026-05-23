import streamlit as st
import requests

# Адрес твоего бэкенда
API_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="AI Tutor Prototype", layout="wide")
st.title("🎓 Адаптивная ИИ-система обучения")

# Инициализация session state
if "student_id" not in st.session_state:
    st.session_state.student_id = "student_1"
if "current_topic" not in st.session_state:
    st.session_state.current_topic = None
if "current_task" not in st.session_state:
    st.session_state.current_task = None
if "answer_submitted" not in st.session_state:
    st.session_state.answer_submitted = False

# Сайдбар
with st.sidebar:
    st.header("👤 Профиль студента")
    st.session_state.student_id = st.text_input(
        "ID студента",
        value=st.session_state.student_id
    )
    if st.button("🔄 Обновить данные"):
        st.cache_data.clear()
        st.rerun()

# Загрузка данных студента
@st.cache_data(ttl=10)
def load_student_data(sid):
    try:
        response = requests.get(f"{API_URL}/student/{sid}", timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        st.error("❌ Не удалось подключиться к бэкенду. Убедись, что uvicorn запущен на порту 8000")
        return None
    except Exception as e:
        st.error(f"Ошибка: {e}")
        return None

# Основная логика
data = load_student_data(st.session_state.student_id)

if data is not None:
    student = data["student"]
    available_topics = data["available_topics"]
    graph_nodes = data["knowledge_graph_nodes"]

    # Карточки статистики
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("✨ XP", student["xp"])
    with col2:
        st.metric("🏆 Уровень", student["level"])
    with col3:
        st.metric("✅ Изучено тем", len(student["mastered_topics"]))

    # Прогресс-бар до следующего уровня
    xp_in_current_level = student["xp"] % 100
    st.progress(xp_in_current_level / 100, text=f"Прогресс до следующего уровня: {xp_in_current_level}/100 XP")

    # Карта знаний
    st.subheader("🗺️ Карта знаний")
    cols = st.columns(min(len(graph_nodes), 4))

    for idx, (topic_id, metadata) in enumerate(graph_nodes):
        title = metadata.get("title", topic_id)
        with cols[idx % len(cols)]:
            if topic_id in student["mastered_topics"]:
                st.success(f"✅ {title}")
            elif topic_id in available_topics:
                if st.button(f"🔓 {title}", key=f"btn_{topic_id}"):
                    st.session_state.current_topic = topic_id
                    # Очищаем задание и сбрасываем флаг при смене темы
                    st.session_state.current_task = None
                    st.session_state.answer_submitted = False
                    st.rerun()
            else:
                st.warning(f"🔒 {title}")

    # Рабочая область с заданием
    if st.session_state.current_topic:
        # Находим название темы из графа
        topic_title = st.session_state.current_topic
        for tid, metadata in graph_nodes:
            if tid == st.session_state.current_topic:
                topic_title = metadata.get("title", tid)
                break

        st.subheader(f"📝 Тема: {topic_title}")

        if st.button("🤖 Сгенерировать задание", type="primary"):
            with st.spinner("ИИ подбирает материал..."):
                try:
                    resp = requests.post(
                        f"{API_URL}/task/generate",
                        json={
                            "student_id": st.session_state.student_id,
                            "topic_id": st.session_state.current_topic
                        },
                        timeout=10
                    )
                    if resp.status_code == 200:
                        st.session_state.current_task = resp.json()
                        st.session_state.answer_submitted = False  # сброс флага
                    else:
                        st.error(f"❌ {resp.json().get('error', 'Ошибка генерации')}")
                except Exception as e:
                    st.error(f"Ошибка подключения: {e}")

        # Отображение текущего задания
        if st.session_state.current_task and "task" in st.session_state.current_task:
            task = st.session_state.current_task["task"]
            st.info(f"📖 **Задание**:\n{task['content']}")
            st.caption(f" Сложность: {task['difficulty'].upper()}")

            # ГЛАВНОЕ ИСПРАВЛЕНИЕ: используем form для кнопок
            if st.session_state.answer_submitted:
                st.info("ℹ️ Ответ отправлен. Нажмите '🔄 Обновить данные' для продолжения.")
            else:
                # Используем form для атомарности
                with st.form(key="answer_form"):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        submit_correct = st.form_submit_button("✅ Я решил правильно", type="primary")
                        if submit_correct:
                            st.session_state.answer_submitted = True
                            try:
                                requests.post(
                                    f"{API_URL}/task/submit",
                                    json={
                                        "student_id": st.session_state.student_id,
                                        "topic_id": st.session_state.current_topic,
                                        "is_correct": True
                                    },
                                    timeout=5
                                )
                                st.success("🎉 Отлично! +50 XP")
                                st.cache_data.clear()
                                st.rerun()
                            except Exception as e:
                                st.error(f"Ошибка: {e}")
                                st.session_state.answer_submitted = False

                    with col_b:
                        submit_wrong = st.form_submit_button("❌ Не получилось")
                        if submit_wrong:
                            st.session_state.answer_submitted = True
                            try:
                                requests.post(
                                    f"{API_URL}/task/submit",
                                    json={
                                        "student_id": st.session_state.student_id,
                                        "topic_id": st.session_state.current_topic,
                                        "is_correct": False
                                    },
                                    timeout=5
                                )
                                st.warning("💪 Попробуй ещё раз! +10 XP")
                                st.cache_data.clear()
                                st.rerun()
                            except Exception as e:
                                st.error(f"Ошибка: {e}")
                                st.session_state.answer_submitted = False
else:
    st.warning("⚠️ Не удалось загрузить данные.")