from sqlmodel import Session, select
from db.engine import engine
from db.models import Topic, TopicPrerequisite


def migrate():
    with Session(engine) as session:
        topics = session.exec(select(Topic)).all()

        for topic in topics:
            if topic.prerequisites:  # старое поле
                prereq_ids = [int(x) for x in topic.prerequisites.split(',') if x]
                for prereq_id in prereq_ids:
                    link = TopicPrerequisite(
                        topic_id=topic.id,
                        prerequisite_id=prereq_id
                    )
                    session.add(link)

        session.commit()
        print(f"✅ Мигрировано {len(topics)} тем")


if __name__ == "__main__":
    migrate()