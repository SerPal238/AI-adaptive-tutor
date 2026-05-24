/**
 * 📡 API-клиент для взаимодействия с бэкендом
 * Все fetch-запросы вынесены сюда для централизованной обработки ошибок
 */

import { CONFIG } from './config.js';
/**
 * Базовая функция для запросов с обработкой ошибок
 */
async function request(endpoint, options = {}) {
    const url = `${CONFIG.api.baseUrl}${endpoint}`;

    const config = {
        headers: {
            'Content-Type': 'application/json',
            ...options.headers,
        },
        timeout: CONFIG.api.timeout,
        ...options,
    };

    // Добавляем таймаут через AbortController
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), config.timeout);

    try {
        const response = await fetch(url, {
            ...config,
            signal: controller.signal,
        });
        clearTimeout(timeoutId);

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `HTTP ${response.status}`);
        }

        return await response.json();
    } catch (error) {
        if (error.name === 'AbortError') {
            throw new Error('Превышено время ожидания ответа сервера');
        }
        if (error.message.includes('Failed to fetch')) {
            throw new Error(CONFIG.texts.error.network);
        }
        throw error;
    }
}

// ===== ЭКСПОРТИРУЕМЫЕ МЕТОДЫ =====

/**
 * Получить данные студента
 */
export async function getStudent(studentId) {
    return request(`/student/${studentId}`);
}

/**
 * Сгенерировать задание
 */
export async function generateTask(studentId, topic) {
    // 🔹 Извлекаем ID из объекта темы (если это объект)
    const topicId = topic?.id || topic;

    console.log('📤 Отправляю запрос на генерацию:', { student_id: studentId, topic_id: topicId });

    return request('/task/generate', {
        method: 'POST',
        body: JSON.stringify({
            student_id: studentId,
            topic_id: topicId
        }),
    });
}

/**
 * Отправить ответ на задание
 */
export async function submitAnswer(studentId, topic, taskId, isCorrect, studentAnswer = '') {
    const topicId = topic?.id || topic;
    const body = {
        student_id: studentId,
        topic_id: topicId,
        task_id: taskId,
        is_correct: isCorrect,
    };

    // 🔹 Если есть текст ответа — добавляем его
    if (studentAnswer && studentAnswer.trim().length > 0) {
        body.student_answer = studentAnswer;
        console.log('📤 Отправляю student_answer:', studentAnswer);
    } else {
        console.warn('⚠️ student_answer пустой!');
    }

    return request('/task/submit', {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

/**
 * Инициализировать нового студента (для тестов)
 */
export async function initStudent(studentId, name = 'Студент') {
    return request(`/student/${studentId}/init`, {
        method: 'POST',
        body: JSON.stringify({ name }),
    });
}

/**
 * Получить список всех студентов
 */
export async function getStudents() {
    return request('/students');  // GET-запрос, вернёт массив студентов
}

/**
 * Запросить подробное объяснение задания
 */
export async function requestExplanation(studentId, topicId, taskId) {

    return request('/task/explain', {
        method: 'POST',
        body: JSON.stringify({
            student_id: Number(studentId),
            topic_id: Number(topicId?.id || topicId),
            task_id: Number(taskId),
            is_correct: false,
            student_answer: ""
        }),
    });
}