from __future__ import annotations

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.knowledge_routes import _ensure_extracting_paper
from app.models import knowledge as knowledge_model  # noqa: F401
from app.models import task as task_model  # noqa: F401
from app.models import user as user_model  # noqa: F401
from app.models.task import Task, TaskStatus


def test_ensure_extracting_paper_creates_real_paper_id_for_new_task():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    task = Task(
        task_id="task-1",
        filename="paper.pdf",
        user_id=7,
        status=TaskStatus.COMPLETED,
    )

    with Session(engine) as session:
        session.add(task)
        session.commit()

        paper = _ensure_extracting_paper(
            session=session,
            task=task,
            user_id=7,
            extraction_model="model-a",
        )

        assert paper.id != "pending"
        assert paper.task_id == "task-1"
        assert paper.user_id == 7
        assert paper.extraction_status == "extracting"
        assert paper.extraction_model == "model-a"


def test_ensure_extracting_paper_reuses_existing_paper_for_task():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    task = Task(
        task_id="task-1",
        filename="paper.pdf",
        user_id=7,
        status=TaskStatus.COMPLETED,
    )

    with Session(engine) as session:
        session.add(task)
        session.commit()

        first = _ensure_extracting_paper(
            session=session,
            task=task,
            user_id=7,
            extraction_model="model-a",
        )
        second = _ensure_extracting_paper(
            session=session,
            task=task,
            user_id=7,
            extraction_model="model-a",
        )

        assert second.id == first.id
