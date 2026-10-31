"""Bound admission before reading PDF bytes; keep queued work on disk."""

from collections import Counter
from contextlib import contextmanager

from fastapi import HTTPException

from .background_tasks import create_tracked_task


class JobQueue:
    def __init__(self, config):
        self.config = config
        self.owners = Counter()

    @contextmanager
    def reserve(self, user_id):
        if (
            sum(self.owners.values()) >= self.config.max_pending
            or self.owners[user_id] >= self.config.max_pending_per_user
        ):
            raise HTTPException(429, "待处理任务已满，请等待已有任务完成", headers={"Retry-After": "30"})
        self.owners[user_id] += 1
        started = False

        def start(coro, background=None):
            nonlocal started
            if background is not None:

                async def run():
                    try:
                        await coro
                    finally:
                        self.release(user_id)

                background.add_task(run)
                started = True
                return None
            task = create_tracked_task(coro)
            started = True
            task.add_done_callback(lambda _: self.release(user_id))
            return task

        try:
            yield start
        finally:
            if not started:
                self.release(user_id)

    def release(self, user_id):
        self.owners[user_id] -= 1
        if self.owners[user_id] <= 0:
            del self.owners[user_id]
