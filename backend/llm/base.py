# backend/llm/base.py
"""
Абстрактный интерфейс для провайдеров нейросетей.
Позволяет легко заменить Ollama на OpenAI, Yandex GPT и т.д.
"""
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Optional


class LLMConfig(BaseModel):
    """Конфигурация вызова нейросети"""
    model: str = "qwen2.5:7b"
    temperature: float = 0.3
    max_tokens: int = 512
    timeout: float = 120.0


class TaskOutput(BaseModel):
    question: str
    expected_answer: str = ""
    answer_type: str = "code" # "code", "value", "text"
    difficulty: str = "medium"
    explanation: Optional[str] = "Объяснение не предоставлено"


class LLMProvider(ABC):
    @abstractmethod
    async def generate_task(self, prompt: str, config: LLMConfig) -> TaskOutput:
        pass

    @abstractmethod
    async def verify_answer(self, prompt: str, config: LLMConfig) -> dict:
        """Проверяет ответ студента"""
        pass

    @abstractmethod
    async def explain_task(self, prompt: str, config: LLMConfig) -> dict:
        """Генерирует подробное объяснение"""
        pass