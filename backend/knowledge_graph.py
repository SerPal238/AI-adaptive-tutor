import networkx as nx
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from db.models import Topic


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
            # Если БД пуста — создаём дефолтные темы (seed)
            await self._seed_default_topics(session)
            # Рекурсивно перезагружаем граф уже с данными
            return await self.load_from_db(session)

        # 2. Добавляем узлы (темы) в граф
        for topic in topics:
            self.graph.add_node(
                topic.id,
                name=topic.name,
                subject=topic.subject,
                difficulty=3  # Можно добавить поле difficulty в модель Topic
            )

        # 3. Добавляем рёбра (зависимости) на основе prerequisites
        for topic in topics:
            if topic.prerequisites:
                # Ожидаем формат: "1,3,5" → строка с ID через запятую
                try:
                    prereq_ids = [int(x.strip()) for x in topic.prerequisites.split(',') if x.strip()]
                    for prereq_id in prereq_ids:
                        # Добавляем ребро: prereq_id → topic.id
                        # (чтобы изучить topic.id, нужно пройти prereq_id)
                        if self.graph.has_node(prereq_id):
                            self.graph.add_edge(prereq_id, topic.id)
                except (ValueError, AttributeError) as e:
                    print(f"⚠️ Ошибка парсинга prerequisites для темы {topic.id}: {e}")

        self._is_loaded = True
        print(f"✅ Граф знаний загружен: {len(self.graph.nodes())} тем, {len(self.graph.edges())} связей")

    async def _seed_default_topics(self, session: AsyncSession):
        """
        Создаёт начальные темы, если БД пуста.
        Запускается автоматически при первом старте.
        """
        default_topics = [
            Topic(id=1, name="Введение в Python", subject="Программирование", prerequisites=""),
            Topic(id=2, name="Переменные и типы данных", subject="Программирование", prerequisites="1"),
            Topic(id=3, name="Циклы", subject="Программирование", prerequisites="2"),
            Topic(id=4, name="Функции", subject="Программирование", prerequisites="3"),
            Topic(id=5, name="ООП", subject="Программирование", prerequisites="4"),

        ]

        for t in default_topics:
            # Проверяем, нет ли уже такой темы (защита от дублей при перезапуске)
            existing = await session.get(Topic, t.id)
            if not existing:
                session.add(t)

        await session.commit()
        print("Созданы дефолтные темы в БД")

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