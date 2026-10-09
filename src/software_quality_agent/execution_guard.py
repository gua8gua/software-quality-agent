"""Host deadlines around SDK Runner, not a replacement model/tool loop."""
import asyncio
from contextlib import suppress
from datetime import UTC, datetime


class NoBusinessProgress(RuntimeError):
    code = "no_business_progress"


async def with_progress_deadline(operation, store, idle_seconds):
    running = asyncio.create_task(operation)
    try:
        while not running.done():
            stamp = store.data.get("last_business_progress_at")
            elapsed = (datetime.now(UTC) - datetime.fromisoformat(stamp)).total_seconds() if stamp else 0
            remaining = idle_seconds - elapsed
            if remaining <= 0:
                raise NoBusinessProgress("No new material or saved business fact within the configured progress deadline")
            await asyncio.wait({running}, timeout=min(remaining, 5))
        return await running
    finally:
        if not running.done():
            running.cancel()
            with suppress(asyncio.CancelledError):
                await running
