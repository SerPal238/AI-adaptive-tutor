/**
 * 🎛️ КОНФИГУРАЦИЯ ПРИЛОЖЕНИЯ
 * Меняйте значения здесь — изменения применятся везде
 */

export const CONFIG = {
    // 🔗 API настройки
    api: {
        baseUrl: 'http://localhost:8000',
        timeout: 120000, // 2 минуты таймаут
    },

    // 👤 Студент по умолчанию
    student: {
        defaultId: '1',
        // Можно добавить список студентов для выбора
        // list: [{ id: '1', name: 'Иван' }, { id: '2', name: 'Мария' }]
    },

    // 🎨 Тексты интерфейса (легко локализовать)
    texts: {
        loading: 'Генерация задания...',
        error: {
            network: 'Не удалось подключиться к серверу. Проверьте, запущен ли бэкенд.',
            generation: 'Ошибка при создании задания. Попробуйте ещё раз.',
            submit: 'Не удалось отправить ответ.',
        },
        feedback: {
            correct: '✅ Отлично! Правильный ответ.',
            wrong: '❌ Неверно. Попробуйте разобраться в объяснении.',
            xpGain: (xp) => `+${xp} XP`,
        },
        difficulty: {
            easy: 'Лёгкий',
            medium: 'Средний',
            hard: 'Сложный',
        },
    },

    // ♿ Настройки доступности
    a11y: {
        announceDelay: 100, // задержка перед озвучкой для скринридеров (мс)
        focusTrap: false,   // пока не нужно, но можно включить
    },

    // 🎮 Геймификация
    gamification: {
        xpPerCorrect: 25,
        xpPerWrong: 5,
        xpPerLevel: 100,
    },
};

// Экспорт отдельных значений для удобства
export const API_URL = CONFIG.api.baseUrl;
export const DEFAULT_STUDENT_ID = CONFIG.student.defaultId;