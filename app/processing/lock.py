"""
Очередь обработки.

Одновременно обрабатывается только одно видео (FFmpeg + Whisper
нагружают процессор полностью). Остальные задачи ждут в очереди.
"""

import asyncio
from contextlib import asynccontextmanager


_processing_lock = asyncio.Lock()
_waiting = 0


def is_processing() -> bool:
    return _processing_lock.locked()


def queue_size() -> int:
    """
    Сколько задач ждёт (не считая выполняемую).
    """

    return _waiting


@asynccontextmanager
async def processing_slot():
    """
    Ждёт своей очереди и удерживает слот на время обработки.
    """

    global _waiting

    _waiting += 1

    try:
        await _processing_lock.acquire()
    finally:
        _waiting -= 1

    try:
        yield
    finally:
        _processing_lock.release()
