/**
 * 🎨 UI-утилиты: рендеринг компонентов интерфейса
 * Чистые функции, которые принимают данные и возвращают HTML/управляют DOM
 */

import { CONFIG } from './config.js';

/**
 * Отрисовать статистику студента (строго по твоим HTML ID)
 */
export function renderStats(rawData) {
    console.log('🎨 renderStats вызван. Сырые данные:', rawData);

    // Поддержка двух форматов: { student: {...} } или плоский объект
    const student = rawData?.student || rawData;
    if (!student) {
        console.warn('⚠️ renderStats: данные студента отсутствуют');
        return;
    }

    try {
        // 1. XP
        const xpEl = document.getElementById('xp-value');
        if (xpEl) {
            xpEl.textContent = student.xp ?? 0;
            console.log('✅ XP:', xpEl.textContent);
        }

        // 2. Уровень
        const levelEl = document.getElementById('level-value');
        if (levelEl) {
            levelEl.textContent = student.level ?? 1;
            console.log('✅ Уровень:', levelEl.textContent);
        }

        // 3. Изучено тем
        const masteredEl = document.getElementById('mastered-value');
        if (masteredEl) {
            // Берем длину массива или число, если бэк вернул иначе
            const count = Array.isArray(student.mastered_topics)
                ? student.mastered_topics.length
                : (student.mastered_count ?? 0);
            masteredEl.textContent = count;
        }

        // 4. Прогресс-бар
        const progressFill = document.getElementById('progress-fill');
        const progressText = document.getElementById('progress-text');
        if (progressFill && progressText && student.xp !== undefined) {
            const xpInLevel = student.xp % 100;
            const percent = Math.min(100, Math.max(0, xpInLevel));

            progressFill.style.width = `${percent}%`;
            progressText.textContent = `${xpInLevel}/100 XP до следующего уровня`;
            console.log(`✅ Прогресс: ${percent}%`);
        }

        // 5. Dropdown (student-select)
        const selectEl = document.getElementById('student-select');
        if (selectEl && student.name) {
            let option = selectEl.querySelector(`option[value="${student.id}"]`);
            if (!option) {
                option = document.createElement('option');
                option.value = student.id;
                selectEl.appendChild(option);
            }
            option.textContent = `${student.name} (Ур.${student.level || 1}, ${student.xp || 0} XP)`;
            option.selected = true;
            console.log('✅ Dropdown обновлен');
        }

    } catch (err) {
        console.error('❌ Ошибка внутри renderStats:', err);
    }
}


/**
 * Отрисовать карту знаний
 */
export function renderTopics(topics, masteredTopics, unlockedTopics, masteryScores = {}, onSelect) {
    const container = document.getElementById('topics-container');
    container.innerHTML = '';

    // Если темы пришли как массив объектов (из графа)
    const topicsArray = Array.isArray(topics) ? topics : Object.entries(topics);

    topicsArray.forEach(([topicId, metadata]) => {
        // 🔹 Извлекаем название (поддержка разных форматов)
        const title = typeof metadata === 'object'
            ? (metadata.title || metadata.name || `Тема #${topicId}`)
            : metadata;

        const isMastered = masteredTopics?.includes(topicId);
        const isUnlocked = unlockedTopics?.includes(topicId);

        const btn = document.createElement('button');
        btn.className = `topic-card ${isMastered ? 'topic-card--mastered' : isUnlocked ? 'topic-card--unlocked' : 'topic-card--locked'}`;
        btn.setAttribute('role', 'listitem');
        btn.setAttribute('aria-label', `${title} ${isMastered ? '(изучено)' : isUnlocked ? '(доступно)' : '(заблокировано)'}`);

        // 🔹 Вычисляем прогресс для визуализации
        const masteryScore = masteryScores[topicId] ?? 0;
        const progressPercent = Math.round(masteryScore * 100);

        btn.innerHTML = `
            <span class="topic-card__icon" aria-hidden="true">
                ${isMastered ? '✅' : isUnlocked ? '🔓' : '🔒'}
            </span>
            <span class="topic-card__title">${title}</span>
            
            <!-- 🔹 ПРОГРЕСС-БАР ТЕМЫ -->
            <div class="topic-card__progress" aria-hidden="true">
                <div class="topic-card__progress-fill" style="width: ${progressPercent}%"></div>
            </div>
            <span class="topic-card__progress-text">${progressPercent}%</span>
        `;
        if (isUnlocked && !isMastered) {
            // 🔹 СОБИРАЕМ ПОЛНЫЙ ОБЪЕКТ ТЕМЫ
            const topicObject = {
                id: topicId,
                name: typeof metadata === 'object' ? metadata.name : title,
                title: typeof metadata === 'object' ? metadata.title : title,
                // Добавляем остальные поля из метаданных, если они есть
                ...(typeof metadata === 'object' ? metadata : {})
            };

            // 🔹 Передаём ВЕСЬ объект в onSelect
            btn.onclick = () => onSelect(topicObject);
            btn.tabIndex = 0;
        } else {
            btn.disabled = true;
        }

        container.appendChild(btn);
    });
}

/**
 * Отрисовать задание с полем ввода
 * @param {Object} task - Данные задания от API
 * @param {string} topicName - Название темы (опционально)
 */
export function renderTask(task, topicName) {
    // 🔹 ОБНОВЛЯЕМ ЗАГОЛОВОК С НАЗВАНИЕМ ТЕМЫ
    const heading = document.getElementById('task-heading');
    if (heading && topicName) {
        heading.textContent = `📝 Тема: ${topicName}`;
        console.log('✅ Заголовок обновлён:', heading.textContent);
    }

    // Обновляем мета-информацию
    const difficultyEl = document.getElementById('task-difficulty');
    const masteryEl = document.getElementById('task-mastery');

    if (difficultyEl) {
        difficultyEl.textContent = CONFIG.texts.difficulty[task.difficulty] || task.difficulty;
    }
    if (masteryEl) {
        masteryEl.textContent = `Mastery: ${task.mastery_level?.toFixed(2) || '0.0'}`;
    }

    // Обновляем вопрос
    const questionEl = document.getElementById('task-question');
    if (questionEl) {
        questionEl.textContent = task.question;
    }

    // Очищаем и активируем поле ввода
    const input = document.getElementById('student-answer');
    if (input) {
        input.value = '';
        input.disabled = false;
        input.style.borderColor = '';
        input.style.background = '';
        input.focus();
    }

    // Кнопки
    const checkBtn = document.getElementById('check-answer-btn');
    const explainBtn = document.getElementById('explain-btn');

    if (checkBtn) checkBtn.disabled = true;
    if (explainBtn) explainBtn.hidden = true;

    // Скрываем фидбек
    const feedback = document.getElementById('feedback');
    if (feedback) feedback.hidden = true;

    // Показываем блок задания
    const placeholder = document.getElementById('task-placeholder');
    const taskContent = document.getElementById('task-content');

    if (placeholder) placeholder.hidden = true;
    if (taskContent) taskContent.hidden = false;

    console.log('✅ Задание отрисовано');
}

/**
 * Отображает код с переносами строк
 */
function formatCodeForDisplay(code) {
    // Заменяем \n на реальные переносы
    return code
        .replace(/\\n/g, '\n')      // \n → перенос строки
        .replace(/\\t/g, '    ')    // \t → 4 пробела (табуляция)
        .replace(/\\"/g, '"')       // \" → "
        .replace(/\\\\/g, '\\');    // \\ → \
}

/**
 * Форматирует текст с выделением кода
 */
export function formatCodeInText(text) {
    if (!text) return '';

    // 1. Экранируем HTML-теги (защита от XSS)
    let safeText = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

    // 2. Обрабатываем блоки кода: ```код```
    safeText = safeText.replace(/```([\s\S]*?)```/g, (match, code) => {
        const formatted = code.trim()
            .replace(/\n/g, '<br>')
            .replace(/\t/g, '&nbsp;&nbsp;&nbsp;&nbsp;');
        return `<pre class="code-block"><code>${formatted}</code></pre>`;
    });

    // 3. Обрабатываем инлайн-код: `код`
    safeText = safeText.replace(/`([^`]+)`/g, '<code class="code-inline">$1</code>');

    // 4. Обычные переносы строк → <br>
    safeText = safeText.replace(/\n/g, '<br>');

    return safeText;
}

/**
 * Показать обратную связь после проверки ответа
 */
export function showFeedback(isCorrect, explanation, xpGain, expectedAnswer = '') {
    console.log('📢 showFeedback вызвана:', { isCorrect, explanation, xpGain });

    const feedback = document.getElementById('feedback');
    const messageEl = document.getElementById('feedback-message');
    const explanationEl = document.getElementById('feedback-explanation');

    if (!feedback || !messageEl || !explanationEl) {
        console.error('❌ Элементы фидбека не найдены!');
        return;
    }

    feedback.className = `feedback feedback--${isCorrect ? 'success' : 'error'}`;

    const messageText = isCorrect
        ? `${CONFIG.texts.feedback.correct} ${CONFIG.texts.feedback.xpGain(xpGain)}`
        : `${CONFIG.texts.feedback.wrong} ${CONFIG.texts.feedback.xpGain(xpGain)}`;

    messageEl.textContent = messageText;

    // 🔹 Форматируем объяснение с кодом
    let fullExplanation = explanation || '';

    if (!isCorrect && expectedAnswer) {
        const formattedExpected = formatCodeForDisplay(expectedAnswer);
        // Оборачиваем эталонный ответ в блок кода
        fullExplanation += `\n\n📝 Эталонный ответ:\n\`\`\`\n${formattedExpected}\n\`\`\``;
    }

    // 🔹 Применяем форматирование и используем innerHTML
    explanationEl.innerHTML = formatCodeInText(fullExplanation);

    feedback.hidden = false;
    feedback.style.display = 'block';

    console.log('✅ Фидбек показан');
    feedback.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/**
 * Очистить интерфейс задания
 */
export function resetTaskView() {
    const placeholder = document.getElementById('task-placeholder');
    const taskContent = document.getElementById('task-content');
    const feedback = document.getElementById('feedback');
    const generateBtn = document.getElementById('generate-btn');
    const nextTaskBtn = document.getElementById('next-task-btn');
    const taskQuestion = document.getElementById('task-question');
    const optionsContainer = document.getElementById('options-container');

    // 🔹 Проверяем, что элементы существуют
    if (placeholder) placeholder.hidden = false;
    if (taskContent) taskContent.hidden = true;
    if (feedback) feedback.hidden = true;
    if (generateBtn) generateBtn.disabled = false;
    if (nextTaskBtn) nextTaskBtn.hidden = true;
    if (taskQuestion) taskQuestion.textContent = '';
    if (optionsContainer) optionsContainer.innerHTML = '';
}

/**
 * Озвучить статус для скринридеров
 */
export function announce(message) {
    const announcer = document.getElementById('sr-announcer');
    // Очистка + задержка для надёжной озвучки
    announcer.textContent = '';
    setTimeout(() => {
        announcer.textContent = message;
    }, CONFIG.a11y.announceDelay);
}

/**
 * Показать/скрыть индикатор загрузки
 */
export function setLoading(isLoading, buttonId = 'generate-btn') {
    const btn = document.getElementById(buttonId);
    if (!btn) return;

    if (isLoading) {
        btn.dataset.originalText = btn.innerHTML;
        btn.innerHTML = `<span class="spinner" aria-hidden="true"></span> ${CONFIG.texts.loading}`;
        btn.disabled = true;
    } else {
        btn.innerHTML = btn.dataset.originalText || btn.textContent;
        btn.disabled = false;
    }
}

/**
 * Показать подробное объяснение решения
 */
export function showDetailedExplanation(mainExplanation, stepByStep = null, hints = null) {
    const feedback = document.getElementById('feedback');
    const messageEl = document.getElementById('feedback-message');
    const explanationEl = document.getElementById('feedback-explanation');

    if (!feedback || !messageEl || !explanationEl) {
        console.error('❌ Элементы фидбека не найдены!');
        return;
    }

    feedback.className = 'feedback feedback--info';

    // 🔹 Формируем HTML с объяснением
    let explanationHTML = `<div class="explanation-block">`;

    // Основное объяснение (с форматированием кода)
    explanationHTML += `<h3 style="margin-top: 0; color: var(--color-primary);">📚 Подробное объяснение</h3>`;
    explanationHTML += `<p style="line-height: 1.6; margin-bottom: 20px;">${formatCodeInText(mainExplanation)}</p>`;

    // Пошаговое решение
    if (stepByStep && stepByStep.length > 0) {
        explanationHTML += `<h4 style="color: var(--color-primary); margin-top: 25px; margin-bottom: 15px;">🔹 Пошаговое решение:</h4>`;
        explanationHTML += `<ol style="padding-left: 20px; line-height: 1.8;">`;
        stepByStep.forEach(step => {
            // 🔹 Форматируем код внутри шагов (inline)
            const formattedStep = formatCodeInText(step)
                .replace(/<pre class="code-block">([\s\S]*?)<\/pre>/g, '<code class="code-inline">$1</code>');
            explanationHTML += `<li style="margin-bottom: 12px;">${formattedStep}</li>`;
        });
        explanationHTML += `</ol>`;
    }

    // Подсказки
    if (hints && hints.length > 0) {
        explanationHTML += `<h4 style="color: var(--color-primary); margin-top: 25px; margin-bottom: 15px;">💡 Ключевые моменты:</h4>`;
        explanationHTML += `<ul style="padding-left: 20px; line-height: 1.8;">`;
        hints.forEach(hint => {
            // 🔹 Форматируем код внутри подсказок (inline)
            const formattedHint = formatCodeInText(hint)
                .replace(/<pre class="code-block">([\s\S]*?)<\/pre>/g, '<code class="code-inline">$1</code>');
            explanationHTML += `<li style="margin-bottom: 8px;">${formattedHint}</li>`;
        });
        explanationHTML += `</ul>`;
    }

    explanationHTML += `</div>`;

    messageEl.textContent = '📖 Вот подробное объяснение решения:';
    messageEl.style.color = 'var(--color-text)';
    explanationEl.innerHTML = explanationHTML;

    feedback.hidden = false;
    feedback.style.display = 'block';

    console.log('✅ Объяснение показано');
    feedback.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
