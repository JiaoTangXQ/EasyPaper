from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlmodel import Session, select

from ..core.config import get_config
from ..core.db import engine
from ..models.reading import ReadingAid, ReadingDocument, ReadingState
from ..models.task import Task, TaskResult, TaskStatus, TaskTitleTranslation


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
            if not task or task.status == TaskStatus.CANCELLED:
                return
            task.status = status
            task.percent = percent
            task.message = message
            task.error = error
            session.add(task)
            session.commit()

    def reading_overview(self, user_id: int) -> dict:
        import json

        with Session(engine) as session:
            states = session.exec(select(ReadingState).where(ReadingState.user_id == user_id)).all()
            documents = {d.task_id: json.loads(d.document_json) for d in session.exec(select(ReadingDocument)).all()}
            result = {}
            for state in states:
                blocks = documents.get(state.task_id, {}).get("blocks", [])
                current = next((b for b in blocks if b.get("id") == state.block_id), None)
                result[state.task_id] = {
                    "block_id": state.block_id,
                    "page": current.get("page") if current else None,
                    "understood_count": len(json.loads(state.understood_json)),
                    "updated_at": state.updated_at.isoformat(),
                }
            return result

    def requeue(self, task_id: str) -> None:
        with Session(engine) as session:
            task = session.get(Task, task_id)
            if task:
                task.status = TaskStatus.PENDING
                task.error = None
                task.percent = 0
                task.message = "已重新排队"
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
            if not task or task.status == TaskStatus.CANCELLED:
                return

            # Save PDF to disk
            if result.pdf_bytes:
                file_path = Path(self.config.storage.temp_dir) / f"{task_id}.pdf"
                file_path.write_bytes(result.pdf_bytes)
                task.result_pdf_path = str(file_path)
                if result.translation_records is not None:
                    import json

                    file_path.with_suffix(".alignment.json").write_text(
                        json.dumps(result.translation_records, ensure_ascii=False)
                    )

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
            if not task or task.status == TaskStatus.CANCELLED:
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
            for model in (ReadingAid, ReadingState, ReadingDocument, TaskTitleTranslation):
                for row in session.exec(select(model).where(model.task_id == task_id)).all():
                    session.delete(row)
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
                # Preserve user-owned sources so interrupted exports can be retried
                # and the reading workspace remains usable after a restart.
                # A normal user upload lives in the configured library directory
                # and is retained for the reader. Test/legacy paths outside it
                # are temporary and retain the old cleanup behaviour.
                library_root = Path(self.config.storage.temp_dir).resolve()
                paths = tuple(
                    path
                    for path in (task.original_pdf_path, task.result_pdf_path, task.result_dual_pdf_path)
                    if task.user_id is None or not path or library_root not in Path(path).resolve().parents
                )
                for path in paths:
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
        _terminal = [TaskStatus.COMPLETED, TaskStatus.ERROR, TaskStatus.CANCELLED]
        with Session(engine) as session:
            statement = select(Task).where(
                Task.created_at < cutoff,
                Task.status.in_(_terminal),
                Task.user_id.is_(None),
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
