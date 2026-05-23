/**
 * 🎯 ТОЧКА ВХОДА: основная логика приложения
 * Инициализация, обработчики событий, поток данных
 */

import { CONFIG, DEFAULT_STUDENT_ID } from './config.js';
import * as API from './api.js';
import * as UI from './ui.js';

// ===== СОСТОЯНИЕ ПРИЛОЖЕНИЯ =====
const state = {
    studentId: DEFAULT_STUDENT_ID,
    currentTopic: null,
    currentTask: null,
    isSubmitted: false,
};

// 🔹 НОВОЕ: Загрузить список студентов и наполнить селект
async function loadStudentsList() {
    try {
        const students = await API.getStudents();
        const select = document.getElementById('student-select');

        // Очистить текущие опции (оставить только placeholder)
        select.innerHTML = '<option value="" disabled selected>Выберите студента</option>';

        if (students.length === 0) {
            // Если студентов нет — добавить опцию "Создать первого"
            const option = document.createElement('option');
            option.value = 'create-first';
            option.textContent = '📭 Нет студентов. Нажмите, чтобы создать первого';
            select.appendChild(option);
            return;
        }

        // Добавить каждого студента как опцию
        students.forEach(student => {
            const option = document.createElement('option');
            option.value = student.id;
            option.textContent = `${student.name} (Ур.${student.level}, ${student.xp} XP)`;
            select.appendChild(option);
        });

        // 🔹 Выбрать студента по умолчанию (если он есть в списке)
        const defaultExists = students.some(s => s.id == DEFAULT_STUDENT_ID);
        if (defaultExists) {
            select.value = DEFAULT_STUDENT_ID;
            state.studentId = DEFAULT_STUDENT_ID;
        } else if (students[0]) {
            // Если дефолтного нет — выбрать первого в списке
            select.value = students[0].id;
            state.studentId = students[0].id;
        }

    } catch (error) {
        console.error('Ошибка загрузки списка студентов:', error);
        // Фолбэк: оставить хардкод, если сеть упала
        const select = document.getElementById('student-select');
        select.innerHTML = `<option value="${DEFAULT_STUDENT_ID}">Студент ${DEFAULT_STUDENT_ID}</option>`;
    }
}

// ===== ИНИЦИАЛИЗАЦИЯ =====
async function init() {
    // 🔹 НОВОЕ: Сначала загрузить список студентов в селект
    await loadStudentsList();

    // Затем загрузить данные выбранного студента
    await loadStudentData();

    // Навесить обработчики событий
    setupEventListeners();

    // Озвучить загрузку для скринридеров
    UI.announce('Приложение загружено. Выберите тему для начала.');
}

/**
 * Загрузить данные студента с бэкенда
 */
async function loadStudentData() {
    try {
        const data = await API.getStudent(state.studentId);

        UI.renderStats(data.student);


        const topicsData = data.knowledge_graph_nodes || [];
        const masteredTopics = data.mastered_topics || [];
        const unlockedTopics = data.unlocked_topics || [];

        UI.renderTopics(topicsData, masteredTopics, unlockedTopics, handleTopicSelect);

        return data;
    } catch (error) {
        console.error('Ошибка загрузки студента:', error);
        UI.announce(error.message);
        alert(error.message);
        return null;
    }
}

/**
 * Обработчик выбора темы
 * @param {Object} topic - Объект темы { id, name, title, ... }
 */
async function handleTopicSelect(topic) {
    // 🔹 Поддержка: если передали только ID (старый код), ищем имя в графе
    const topicId = topic.id || topic;
    const topicName = topic.name || topic.title || `Тема #${topicId}`;

    console.log(' Выбрана тема:', topicName, '(ID:', topicId + ')');

    state.currentTopic = topic; // Сохраняем ВЕСЬ объект
    state.currentTask = null;
    state.isSubmitted = false;

    UI.resetTaskView();

    // 🔹 Обновляем заголовок с НАЗВАНИЕМ темы
    const heading = document.getElementById('task-heading');
    if (heading) {
        heading.textContent = `📝 Тема: ${topicName}`;
    }

    // 🔹 Загружаем данные студента для отображения mastery
    try {
        const data = await API.getStudent(state.studentId);

        // Находим mastery для выбранной темы
        const masteryData = data.mastery_levels?.find(m => m.topic_id === topicId);
        const masteryLevel = masteryData?.mastery_level || 0.0;

        // Обновляем отображение mastery
        const masteryEl = document.getElementById('task-mastery');
        if (masteryEl) {
            masteryEl.textContent = `Mastery: ${masteryLevel.toFixed(2)}`;
        }
    } catch (error) {
        console.error('Ошибка загрузки mastery:', error);
    }

    UI.announce(`Выбрана тема: ${topicName}. Нажмите "Сгенерировать задание" для начала.`);
}

/**
 * Сгенерировать задание
 */
async function handleGenerateTask() {
    if (!state.currentTopic) {
        UI.announce('Сначала выберите тему из карты знаний');
        alert('👈 Сначала выберите тему выше');
        return;
    }

    UI.setLoading(true);

    try {
        const topicName = state.currentTopic.name ||
                         state.currentTopic.title ||
                         `Тема #${state.currentTopic.id || state.currentTopic}`;

        console.log('📚 Генерируем задание для:', topicName);
        const task = await API.generateTask(state.studentId, state.currentTopic);

        state.currentTask = task;
        state.isSubmitted = false;

        // 🔹 СБРОС FEEDBACK И ПОЛЯ ВВОДА
        const feedback = document.getElementById('feedback');
        if (feedback) {
            feedback.hidden = true;
            feedback.style.display = 'none';
        }

        const input = document.getElementById('student-answer');
        if (input) {
            input.value = '';
            input.disabled = false;
            input.style.borderColor = '';
            input.style.background = '';
        }

        UI.renderTask(task, topicName);
        UI.announce(`Задание сгенерировано. Вопрос: ${task.question}`);

    } catch (error) {
        console.error('Ошибка генерации:', error);
        UI.announce(error.message);
        alert(error.message);
    } finally {
        UI.setLoading(false);
    }
}

/**
 * Отслеживание ввода в текстовое поле
 */
function setupAnswerInputListener() {
    const input = document.getElementById('student-answer');
    const checkBtn = document.getElementById('check-answer-btn');

    input.addEventListener('input', () => {
        checkBtn.disabled = input.value.trim().length === 0;
    });

    // Enter для проверки (Shift+Enter для переноса строки)
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (!checkBtn.disabled) handleCheckAnswer();
        }
    });
}

/**
 * Проверка ответа (полностью делегирует логику бэкенду)
 */
async function handleCheckAnswer() {
    if (!state.currentTask) return;

    const input = document.getElementById('student-answer');
    const studentAnswer = input.value.trim();

    // 🔹 Только базовая валидация: поле не должно быть пустым
    if (!studentAnswer) {
        alert('Введите ответ перед проверкой');
        return;
    }

    // Блокируем интерфейс на время запроса
    input.disabled = true;
    document.getElementById('check-answer-btn').disabled = true;

    try {
        console.log('📤 Отправляю ответ на бэкенд для проверки LLM...');

        // 🔹 Отправляем на бэкенд. is_correct=false не важен, т.к. бэк читает student_answer
        const result = await API.submitAnswer(
            state.studentId,
            state.currentTopic,
            state.currentTask.task_id || state.currentTopic,
            false,
            studentAnswer
        );

        console.log('📊 Полный ответ бэкенда:', result);

        // 🔹 ГЛАВНОЕ: берём вердикт ТОЛЬКО от бэкенда
        const isCorrect = result.is_correct;
        const explanation = result.explanation || state.currentTask.explanation;

        // 🔹 Обновляем Mastery из ответа бэкенда
        const newMastery = result.analysis?.new_mastery_level ?? result.analysis?.new_mastery;
        if (newMastery !== undefined) {
            console.log(`🎯 Mastery обновлён бэкендом: ${newMastery}`);
            const masteryEl = document.getElementById('task-mastery');
            if (masteryEl) masteryEl.textContent = `Mastery: ${newMastery.toFixed(2)}`;
        }

        // 🔹 Показываем фидбек (с эталонным ответом при ошибке)
        UI.showFeedback(
            isCorrect,
            explanation,
            isCorrect ? CONFIG.gamification.xpPerCorrect : CONFIG.gamification.xpPerWrong,
            state.currentTask.expected_answer  // Показывается только при isCorrect=false
        );

        // Озвучка
        UI.announce(isCorrect ? 'Верно! Ответ принят.' : `Неверно. ${explanation}`);

         // 🔹 ОБНОВЛЯЕМ XP И УРОВЕНЬ
        await loadStudentData();

        state.isSubmitted = true;


    } catch (error) {
        console.error('❌ Ошибка проверки:', error);
        alert(error.message || 'Ошибка связи с сервером');
        input.disabled = false;
        document.getElementById('check-answer-btn').disabled = false;
    }
}

/**
 * Навесить обработчики событий
 */
function setupEventListeners() {
    // Выбор студента
    document.getElementById('student-select').addEventListener('change', async (e) => {
        // 🔹 НОВОЕ: Обработка случая "Создать первого студента"
        if (e.target.value === 'create-first') {
            try {
                // Создаём студента с ID=1 (или следующим свободным)
                await API.initStudent(1, 'Новый студент');
                // Перезагружаем список и данные
                await loadStudentsList();
                await loadStudentData();
                UI.announce('Студент создан. Добро пожаловать!');
            } catch (error) {
                console.error('Ошибка создания студента:', error);
                alert('Не удалось создать студента');
            }
            return;
        }

        // Обычное переключение студента
        state.studentId = e.target.value;
        await loadStudentData();
    });

    // Ввод ответа
    setupAnswerInputListener();
    document.getElementById('check-answer-btn').addEventListener('click', handleCheckAnswer);
    document.getElementById('explain-btn').addEventListener('click', handleExplainRequest);

    // Генерация задания
    document.getElementById('generate-btn').addEventListener('click', handleGenerateTask);
}

/**
 * Обработчик кнопки "Объяснить решение"
 */
async function handleExplainRequest() {
    if (!state.currentTask || !state.currentTopic) {
        alert('Задание не сгенерировано');
        return;
    }

    // 🔹 Подтверждение действия
    const topicName = state.currentTopic.name || state.currentTopic.title || 'этой темы';
    const confirmed = confirm(
        `⚠️ Вы уверены, что хотите получить готовое объяснение?\n\n` +
        `• Ваш уровень мастерства темы "${topicName}" снизится\n` +
        `• Опыт за это задание начислен не будет\n` +
        `• Поле ввода будет заблокировано\n\n` +
        `Это поможет вам разобраться в теме, но не засчитается как выполненное задание.`
    );

    if (!confirmed) {
        return; // Пользователь отменил
    }

    // 🔹 Блокируем интерфейс
    const input = document.getElementById('student-answer');
    const explainBtn = document.getElementById('explain-btn');
    const checkBtn = document.getElementById('check-answer-btn');

    if (input) input.disabled = true;
    if (explainBtn) explainBtn.disabled = true;
    if (checkBtn) checkBtn.disabled = true;

    try {
        console.log('💡 Запрашиваю подробное объяснение...');

        const explanation = await API.requestExplanation(
            state.studentId,
            state.currentTopic,
            state.currentTask.task_id,
        );

        console.log('✅ Объяснение получено:', explanation);

        // 🔹 Показываем объяснение
        UI.showDetailedExplanation(
            explanation.detailed_explanation,
            explanation.step_by_step,
            explanation.hints
        );

        // 🔹 Обновляем mastery (снижаем)
        if (explanation.new_mastery !== undefined) {
            const masteryEl = document.getElementById('task-mastery');
            if (masteryEl) {
                masteryEl.textContent = `Mastery: ${explanation.new_mastery.toFixed(2)}`;
            }
        }

        UI.announce('Объяснение показано. Изучите его и переходите к следующему заданию.');

    } catch (error) {
        console.error('❌ Ошибка получения объяснения:', error);
        alert(error.message || 'Не удалось получить объяснение. Попробуйте ещё раз.');

        // Разблокируем интерфейс при ошибке
        if (input) input.disabled = false;
        if (explainBtn) explainBtn.disabled = false;
        if (checkBtn) checkBtn.disabled = false;
    }
}

// ===== ЗАПУСК =====
document.addEventListener('DOMContentLoaded', init);