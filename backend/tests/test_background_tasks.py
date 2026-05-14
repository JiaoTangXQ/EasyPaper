from __future__ import annotations

import asyncio

import pytest

from app.services.background_tasks import create_tracked_task, tracked_task_count


@pytest.mark.asyncio
async def test_create_tracked_task_keeps_reference_until_done():
    baseline = tracked_task_count()
    started = asyncio.Event()
    release = asyncio.Event()

    async def job():
        started.set()
        await release.wait()

    task = create_tracked_task(job())
    await started.wait()

    assert tracked_task_count() == baseline + 1

    release.set()
    await task
    await asyncio.sleep(0)

    assert tracked_task_count() == baseline
