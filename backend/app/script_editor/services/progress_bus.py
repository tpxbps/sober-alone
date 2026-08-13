"""
Progress Event Bus — SSE 进度推送
支持多用户并发：每个 thread_id 有独立的订阅者队列
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# thread_id -> list of subscriber queues
_subscribers: dict[str, list[asyncio.Queue]] = {}


def subscribe(thread_id: str) -> asyncio.Queue:
    """订阅某个工作流的进度事件，返回 asyncio.Queue"""
    queue: asyncio.Queue = asyncio.Queue()
    if thread_id not in _subscribers:
        _subscribers[thread_id] = []
    _subscribers[thread_id].append(queue)
    logger.debug(
        f"SSE subscriber added for thread {thread_id}, total: {len(_subscribers[thread_id])}"
    )
    return queue


def unsubscribe(thread_id: str, queue: asyncio.Queue):
    """取消订阅"""
    if thread_id in _subscribers:
        _subscribers[thread_id] = [q for q in _subscribers[thread_id] if q is not queue]
        if not _subscribers[thread_id]:
            del _subscribers[thread_id]


def publish(thread_id: str, event_type: str, data: Any = None):
    """向某个工作流的所有订阅者发布事件"""
    if thread_id not in _subscribers:
        return
    event = {"type": event_type, "data": data}
    for queue in _subscribers[thread_id]:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(f"SSE queue full for thread {thread_id}, dropping event")
