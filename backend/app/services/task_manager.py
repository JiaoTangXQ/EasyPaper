from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlmodel import Session, select

from ..core.config import get_config
from ..core.db import engine
from ..models.task import Task, TaskResult, TaskStatus


class TaskManager:
    def __init__(self, ttl_minutes: int = 30) -> None:
        self._ttl = timedelta(minutes=ttl_minutes)
        self.config = get_config()
        # Ensure temp dir exists
        Path(self.config.storage.temp_dir).mkdir(parents=True, exist_ok=True)

    def create_task(
        self, filename: str, user_id: int | None = None, mode: str = "translate", highlight: bool = False
    ) -> Task:
        task_id = uuid.uuid4().hex
        task = Task(task_id=task_id, filename=filename, user_id=user_id, mode=mode, highlight=highlight)
        with Session(engine) as session:
            session.add(task)
            session.commit()
            session.refresh(task)
        return task

    def get_task(self, task_id: str) -> Task | None:
        with Session(engine) as session:
            return session.get(Task, task_id)

    def list_tasks(self, user_id: int | None = None, limit: int = 50) -> list[Task]:
        with Session(engine) as session:
            statement = select(Task)
            if user_id:
                statement = statement.where(Task.user_id == user_id)
            statement = statement.order_by(Task.created_at.desc()).limit(limit)
            return session.exec(statement).all()

    def update_progress(
        self, task_id: str, status: TaskStatus, percent: int, message: str, error: str | None = None
    ) -> None:
        with Session(engine) as session:
            task = session.get(Task, task_id)
            if not task:
                return
            task.status = status
            task.percent = percent
            task.message = message
            task.error = error
            session.add(task)
            session.commit()

    def update_original_path(self, task_id: str, path: str) -> None:
        with Session(engine) as session:
            task = session.get(Task, task_id)
            if not task:
                return
            task.original_pdf_path = path
            session.add(task)
            session.commit()

    def set_result(self, task_id: str, result: TaskResult) -> None:
        with Session(engine) as session:
            task = session.get(Task, task_id)
            if not task:
                return

            # Save PDF to disk
            if result.pdf_bytes:
                file_path = Path(self.config.storage.temp_dir) / f"{task_id}.pdf"
                file_path.write_bytes(result.pdf_bytes)
                task.result_pdf_path = str(file_path)

            if result.dual_pdf_bytes:
                dual_file_path = Path(self.config.storage.temp_dir) / f"{task_id}_dual.pdf"
                dual_file_path.write_bytes(result.dual_pdf_bytes)
                task.result_dual_pdf_path = str(dual_file_path)

            task.result_preview_html = result.preview_html
            task.status = TaskStatus.COMPLETED
            task.percent = 100
            task.message = "生成完成"

            session.add(task)
            session.commit()

    def set_highlight_stats(self, task_id: str, stats_json: str) -> None:
        self.set_highlight_result(task_id, stats_json=stats_json, status=None, sentences_json=None)

    def set_highlight_result(
        self,
        task_id: str,
        stats_json: str,
        status: str | None,
        sentences_json: str | None,
    ) -> None:
        with Session(engine) as session:
            task = session.get(Task, task_id)
            if not task:
                return
            task.highlight_stats = stats_json
            task.highlight_status = status
            task.highlight_sentences = sentences_json
            session.add(task)
            session.commit()

    def set_summary(self, task_id: str, summary_json: str) -> None:
        with Session(engine) as session:
            task = session.get(Task, task_id)
            if not task:
                return
            task.summary_json = summary_json
            session.add(task)
            session.commit()

    def set_error(self, task_id: str, message: str) -> None:
        with Session(engine) as session:
            task = session.get(Task, task_id)
            if not task:
                return
            task.status = TaskStatus.ERROR
            task.error = message
            task.message = message
            session.add(task)
            session.commit()

    def delete_task(self, task_id: str) -> None:
        with Session(engine) as session:
            task = session.get(Task, task_id)
            if not task:
                return
            if task.result_pdf_path:
                try:
                    Path(task.result_pdf_path).unlink(missing_ok=True)
                except Exception:
                    pass
            if task.result_dual_pdf_path:
                try:
                    Path(task.result_dual_pdf_path).unlink(missing_ok=True)
                except Exception:
                    pass
            if task.original_pdf_path:
                try:
                    Path(task.original_pdf_path).unlink(missing_ok=True)
                except Exception:
                    pass
            session.delete(task)
            session.commit()

    def fail_orphaned_tasks(self) -> int:
        """Mark non-terminal tasks as errored and drop their temp files.

        Background processing lives only in memory, so any task still mid-flight
        after a restart is orphaned (no coroutine is driving it). Call this once
        at startup so such tasks don't hang forever and leak their temp PDFs.
        Returns the number reconciled.
        """
        _non_terminal = [
            TaskStatus.PENDING,
            TaskStatus.PARSING,
            TaskStatus.REWRITING,
            TaskStatus.RENDERING,
            TaskStatus.HIGHLIGHTING,
        ]
        with Session(engine) as session:
            tasks = session.exec(select(Task).where(Task.status.in_(_non_terminal))).all()
            for task in tasks:
                for path in (task.original_pdf_path, task.result_pdf_path, task.result_dual_pdf_path):
                    if path:
                        try:
                            Path(path).unlink(missing_ok=True)
                        except OSError:
                            pass
                task.status = TaskStatus.ERROR
                task.error = "处理中断（服务重启）"
                task.message = "处理中断（服务重启）"
                session.add(task)
            session.commit()
            return len(tasks)

    def cleanup(self) -> None:
        cutoff = datetime.utcnow() - self._ttl
        _terminal = [TaskStatus.COMPLETED, TaskStatus.ERROR]
        with Session(engine) as session:
            statement = select(Task).where(
                Task.created_at < cutoff,
                Task.status.in_(_terminal),
            )
            expired_tasks = session.exec(statement).all()

            for task in expired_tasks:
                # Delete result PDF if exists
                if task.result_pdf_path:
                    try:
                        Path(task.result_pdf_path).unlink(missing_ok=True)
                    except Exception:
                        pass
                if task.result_dual_pdf_path:
                    try:
                        Path(task.result_dual_pdf_path).unlink(missing_ok=True)
                    except Exception:
                        pass
                # Delete original PDF if exists
                if task.original_pdf_path:
                    try:
                        Path(task.original_pdf_path).unlink(missing_ok=True)
                    except Exception:
                        pass
                session.delete(task)

            session.commit()
