# backend/llm/ollama_client.py
"""
Клиент для локального сервера Ollama.
Работает через HTTP API, асинхронно, с поддержкой JSON-режима.
"""
import httpx
import os
import json
from typing import Optional

from .base import LLMProvider, LLMConfig, TaskOutput


class OllamaClient(LLMProvider):
    """Реализация LLMProvider для Ollama (http://localhost:11434)"""

    def __init__(self, base_url: Optional[str] = None):
        """
        Инициализирует клиент.

        Args:
            base_url: URL Ollama API (по умолчанию http://localhost:11434)
        """
        self.base_url = base_url or os.getenv("OLLAMA_URL", "http://localhost:11434")

    async def generate_task(self, prompt: str, config: LLMConfig) -> TaskOutput:
        """
        Отправляет промпт в Ollama и возвращает валидированный TaskOutput.

        Raises:
            httpx.HTTPError: если запрос не удался
            ValueError: если ответ не валиден
        """
        async with httpx.AsyncClient(timeout=config.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": config.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": config.temperature,
                        "num_predict": config.max_tokens
                    }
                }
            )
            response.raise_for_status()
            data = response.json()

            # Парсим ответ: Ollama возвращает {"response": "строка с JSON"}
            try:
                content = json.loads(data["response"])
                # 🔹 Гарантируем, что все обязательные поля есть
                content.setdefault("expected_answer", "")
                content.setdefault("answer_type", "code")
                content.setdefault("difficulty", "medium")
                content.setdefault("explanation", "Объяснение не предоставлено")

                return TaskOutput(**content)
            except (KeyError, json.JSONDecodeError) as e:
                print(f"⚠️ Ошибка парсинга JSON от LLM: {e}")
                print(f"Raw response: {data.get('response', '')}")
                return TaskOutput(
                    question="Ошибка генерации задания",
                    expected_answer="error",
                    answer_type="text",
                    difficulty="easy",
                    explanation="Не удалось распарсить ответ от нейросети"
                )