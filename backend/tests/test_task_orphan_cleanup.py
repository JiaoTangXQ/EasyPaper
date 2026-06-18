from __future__ import annotations

from pathlib import Path

from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from app.models import task as task_model  # noqa: F401
from app.models import user as user_model  # noqa: F401
from app.models.task import TaskStatus
from app.services import task_manager as task_manager_module
from app.services.task_manager import TaskManager


def _manager(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(task_manager_module, "engine", engine)
    return TaskManager()


def test_fail_orphaned_marks_nonterminal_and_removes_temp_file(monkeypatch, tmp_path):
    manager = _manager(monkeypatch)
    orphan = manager.create_task("stuck.pdf", user_id=1, mode="translate")
    manager.update_progress(orphan.task_id, TaskStatus.REWRITING, 30, "翻译中...")
    original = tmp_path / f"{orphan.task_id}_original.pdf"
    original.write_bytes(b"%PDF-1.4 stuck")
    manager.update_original_path(orphan.task_id, str(original))

    failed = manager.fail_orphaned_tasks()

    assert failed == 1
    updated = manager.get_task(orphan.task_id)
    assert updated.status == TaskStatus.ERROR
    assert updated.error
    assert not original.exists()  # temp PDF cleaned up


def test_fail_orphaned_leaves_terminal_tasks_untouched(monkeypatch, tmp_path):
    manager = _manager(monkeypatch)
    done = manager.create_task("done.pdf", user_id=1, mode="translate")
    manager.update_progress(done.task_id, TaskStatus.COMPLETED, 100, "完成")
    keep = tmp_path / f"{done.task_id}_original.pdf"
    keep.write_bytes(b"%PDF-1.4 done")
    manager.update_original_path(done.task_id, str(keep))

    failed = manager.fail_orphaned_tasks()

    assert failed == 0
    assert manager.get_task(done.task_id).status == TaskStatus.COMPLETED
    assert keep.exists()
