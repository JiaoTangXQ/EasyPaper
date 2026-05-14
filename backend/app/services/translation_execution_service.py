from __future__ import annotations

from pathlib import Path

from ..models.agent import AgentTranslateAccepted, DraftStatus, TranslationDraft
from .background_tasks import create_tracked_task


class TranslationExecutionService:
    def __init__(self, task_manager, processor) -> None:
        self.task_manager = task_manager
        self.processor = processor

    async def submit_draft(self, draft: TranslationDraft) -> AgentTranslateAccepted:
        if draft.status != DraftStatus.READY:
            raise ValueError("Draft is not ready for submission")
        if not draft.source_path:
            raise ValueError("Draft source_path is missing")

        file_bytes = Path(draft.source_path).read_bytes()
        task = self.task_manager.create_task(
            filename=draft.filename,
            mode="translate",
            highlight=bool(draft.highlight),
        )
        original_path = Path(self.task_manager.config.storage.temp_dir) / f"{task.task_id}_original.pdf"
        original_path.write_bytes(file_bytes)
        self.task_manager.update_original_path(task.task_id, str(original_path))
        draft.status = DraftStatus.SUBMITTED

        create_tracked_task(
            self.processor.process(
                task.task_id,
                file_bytes,
                draft.filename,
                mode="translate",
                highlight=bool(draft.highlight),
            )
        )

        return AgentTranslateAccepted(
            draft_id=draft.draft_id,
            task_id=task.task_id,
            status_url=f"/api/agent/v1/tasks/{task.task_id}",
        )
