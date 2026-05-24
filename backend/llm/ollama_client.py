"""
Клиент для локального сервера Ollama.
Работает через HTTP API, асинхронно, с поддержкой JSON-режима.
"""
import httpx
import os
import json
import logging
from typing import Optional

from .base import LLMProvider, LLMConfig, TaskOutput

logger = logging.getLogger(__name__)


class OllamaClient(LLMProvider):
    """Реализация LLMProvider для Ollama (http://localhost:11434)"""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.getenv("OLLAMA_URL", "http://localhost:11434")
        self._client = httpx.AsyncClient(timeout=120.0)

    async def _call_ollama(self, prompt: str, config: LLMConfig) -> str:
        """
        Общий метод для всех вызовов Ollama.
        Возвращает строку с JSON-ответом.
        """
        try:
            response = await self._client.post(
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
            return data.get("response", "")
        except httpx.ConnectError:
            logger.error(f"Не удалось подключиться к Ollama по адресу {self.base_url}")
            raise RuntimeError(f"Не удалось подключиться к Ollama по адресу {self.base_url}")
        except httpx.HTTPStatusError as e:
            logger.error(f"Ollama вернул ошибку: {e.response.status_code}")
            raise RuntimeError(f"Ollama вернул ошибку: {e.response.status_code}")

    async def generate_task(self, prompt: str, config: LLMConfig) -> TaskOutput:
        """
        Отправляет промпт в Ollama и возвращает валидированный TaskOutput.
        ГАРАНТИРОВАННО возвращает TaskOutput (даже при ошибках — с fallback-значениями).
        """
        try:
            content = await self._call_ollama(prompt, config)
            data = json.loads(content)

            # Гарантируем, что все обязательные поля есть
            data.setdefault("expected_answer", "")
            data.setdefault("answer_type", "code")
            data.setdefault("difficulty", "medium")
            data.setdefault("explanation", "Объяснение не предоставлено")

            # Валидируем через Pydantic (отсечёт невалидные значения)
            return TaskOutput(**data)

        except json.JSONDecodeError as e:
            logger.warning(f"⚠️ Не удалось распарсить JSON от LLM: {e}")
            logger.debug(f"Raw content: {content[:200] if 'content' in locals() else 'N/A'}")
            return self._fallback_task_output()

        except Exception as e:
            logger.warning(f"⚠️ Неожиданная ошибка в generate_task: {e}")
            return self._fallback_task_output()

    async def verify_answer(self, prompt: str, config: LLMConfig) -> dict:
        """Проверяет ответ студента"""
        try:
            content = await self._call_ollama(prompt, config)
            result = json.loads(content)
            # Гарантируем нужные поля
            result.setdefault("is_correct", False)
            result.setdefault("explanation", "Объяснение не предоставлено")
            result.setdefault("weakness", "none")
            return result
        except Exception as e:
            logger.warning(f"⚠️ Ошибка в verify_answer: {e}")
            return {
                "is_correct": False,
                "explanation": "Ошибка проверки ответа",
                "weakness": "parse_error"
            }

    async def explain_task(self, prompt: str, config: LLMConfig) -> dict:
        """Генерирует подробное объяснение"""
        try:
            content = await self._call_ollama(prompt, config)
            result = json.loads(content)
            result.setdefault("main_explanation", "Объяснение недоступно")
            result.setdefault("steps", [])
            result.setdefault("hints", [])
            return result
        except Exception as e:
            logger.warning(f"⚠️ Ошибка в explain_task: {e}")
            return {
                "main_explanation": "Не удалось сгенерировать объяснение",
                "steps": [],
                "hints": []
            }

    async def close(self):
        """Закрывает HTTP-клиент (вызывать при остановке приложения)"""
        await self._client.aclose()

    @staticmethod
    def _fallback_task_output() -> TaskOutput:
        """Возвращает безопасный fallback, когда LLM не ответил корректно"""
        return TaskOutput(
            question="Ошибка генерации задания. Попробуйте ещё раз.",
            expected_answer="",
            answer_type="text",
            difficulty="easy",
            explanation="Не удалось получить задание от нейросети"
        )