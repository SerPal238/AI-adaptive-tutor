import networkx as nx
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from db.models import Topic, TopicPrerequisite
import logging

logger = logging.getLogger(__name__)

class KnowledgeGraphManager:
    def __init__(self):
        # Создаём направленный граф (Directed Graph)
        self.graph = nx.DiGraph()
        self._is_loaded = False

    async def load_from_db(self, session: AsyncSession):
        """
        Загружает темы и связи из базы данных в память.
        Вызывается один раз при старте сервера.
        """
        self.graph.clear()

        # 1. Загружаем все темы из БД
        stmt = select(Topic)
        result = await session.exec(stmt)
        topics = result.all()

        if not topics:
            await self._seed_default_topics(session)
            return await self.load_from_db(session)

        # 2. Добавляем узлы (темы) в граф
        for topic in topics:
            self.graph.add_node(
                topic.id,
                name=topic.name,
                subject=topic.subject
            )

        # 🔹 3. НОВОЕ: Загружаем все связи prerequisites одной выборкой
        prereq_stmt = select(TopicPrerequisite)
        prereq_result = await session.exec(prereq_stmt)
        links = prereq_result.all()

        # 4. Добавляем рёбра в граф
        for link in links:
            if self.graph.has_node(link.prerequisite_id) and self.graph.has_node(link.topic_id):
                self.graph.add_edge(link.prerequisite_id, link.topic_id)

        self._is_loaded = True
        logger.info(f"✅ Граф знаний загружен: {len(self.graph.nodes())} тем, {len(self.graph.edges())} связей")

    async def _seed_default_topics(self, session: AsyncSession):
        """
        Создаёт начальные темы и связи между ними.
        Запускается автоматически при первом старте.
        """
        # 1. Определяем темы
        default_topics = [
            Topic(id=1, name="Введение в Python", subject="Программирование"),
            Topic(id=2, name="Переменные и типы данных", subject="Программирование"),
            Topic(id=3, name="Циклы", subject="Программирование"),
            Topic(id=4, name="Функции", subject="Программирование"),
            Topic(id=5, name="ООП", subject="Программирование"),
        ]

        # 2. Добавляем темы (если их ещё нет)
        for t in default_topics:
            existing = await session.get(Topic, t.id)
            if not existing:
                session.add(t)
        await session.commit()

        # 3. Определяем связи prerequisites
        # (topic_id, prerequisite_id) — "чтобы изучить topic_id, нужно пройти prerequisite_id"
        default_prereqs = [
            (2, 1),  # Переменные требуют Введение
            (3, 2),  # Циклы требуют Переменные
            (4, 3),  # Функции требуют Циклы
            (5, 4),  # ООП требует Функции
        ]

        # 4. Создаём связи (если их ещё нет)
        for topic_id, prereq_id in default_prereqs:
            existing = await session.get(TopicPrerequisite, (topic_id, prereq_id))
            if not existing:
                session.add(TopicPrerequisite(topic_id=topic_id, prerequisite_id=prereq_id))

        await session.commit()
        logger.info("✅ Созданы дефолтные темы и связи в БД")

    # ─────────────────────────────────────────────────────────────
    # 🔹 Синхронные методы (работают с уже загруженным в память графом)
    # ─────────────────────────────────────────────────────────────

    def get_prerequisites(self, topic_id: int) -> list[int]:
        """
        Возвращает список ID тем, которые нужно пройти ПЕРЕД этой темой.
        """
        if not self._is_loaded:
            print("⚠️ Граф ещё не загружен! Вызовите load_from_db() перед использованием.")
            return []
        return list(self.graph.predecessors(topic_id))

    def get_unlocked_topics(self, mastered_ids: set[int]) -> list[int]:
        """
        Возвращает список ID тем, которые открыты для изучения.
        mastered_ids: множество ID тем, где mastery_level >= 0.9
        """
        if not self._is_loaded:
            return []

        available = []
        for node_id in self.graph.nodes():
            # Пропускаем уже изученные темы
            if node_id in mastered_ids:
                continue

            # Получаем всех предков темы
            prereqs = set(self.graph.predecessors(node_id))

            # Тема доступна, если все предки изучены (или их нет)
            if prereqs.issubset(mastered_ids):
                available.append(node_id)

        return available

    def get_topic_info(self, topic_id: int) -> dict | None:
        """
        Возвращает метаданные темы (название, предмет) по ID.
        """
        if self.graph.has_node(topic_id):
            return self.graph.nodes[topic_id]
        return None

    def get_all_topics(self) -> list[dict]:
        """
        Возвращает список всех тем с метаданными (для отладки/админки).
        """
        return [
            {"id": nid, **data}
            for nid, data in self.graph.nodes(data=True)
        ]


# ─────────────────────────────────────────────────────────────
# 🔹 Глобальный экземпляр (синглтон)
# ─────────────────────────────────────────────────────────────
graph_manager = KnowledgeGraphManager()