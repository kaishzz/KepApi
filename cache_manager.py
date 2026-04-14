import asyncio
from typing import Any


class SnapshotCacheStore:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._items: list[Any] = []
        self._updated_at: str | None = None
        self._last_error: str | None = None

    async def replace(
        self, items: list[Any], *, updated_at: str | None, last_error: str | None
    ):
        async with self._lock:
            self._items = list(items)
            self._updated_at = updated_at
            self._last_error = last_error

    async def set_error(self, error: str):
        async with self._lock:
            self._last_error = error

    async def get_items(self) -> list:
        async with self._lock:
            return list(self._items)

    async def snapshot(self, *, items_key: str = "servers") -> dict:
        async with self._lock:
            return {
                "updated_at": self._updated_at,
                "last_error": self._last_error,
                items_key: list(self._items),
            }


async def stop_background_task(task: asyncio.Task | None, *, timeout: float = 2.0):
    if task is None:
        return
    try:
        await asyncio.wait_for(task, timeout=timeout)
    except asyncio.CancelledError:
        pass
    except asyncio.TimeoutError:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except BaseException:
            pass
