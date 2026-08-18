"""Thread-safe workflow progress snapshots shared by conversion and assets."""

from __future__ import annotations

import threading
from collections.abc import Callable
from copy import deepcopy

from app.script_editor.services.progress_bus import publish


class WorkflowProgressRegistry:
    def __init__(self, event_type: str):
        self.event_type = event_type
        self._lock = threading.Lock()
        self._progress: dict[str, dict] = {}
        self._threads: dict[str, str] = {}

    def register_thread(self, script_id: str, thread_id: str) -> None:
        with self._lock:
            self._threads[script_id] = thread_id

    def thread_id(self, script_id: str) -> str | None:
        with self._lock:
            return self._threads.get(script_id)

    def init(self, script_id: str, phases: list[dict]) -> None:
        with self._lock:
            self._progress[script_id] = {
                "phases": deepcopy(phases),
                "isComplete": False,
            }

    def mutate(self, script_id: str, mutation: Callable[[dict], None]) -> None:
        with self._lock:
            progress = self._progress.get(script_id)
            if progress:
                mutation(progress)

    def update_task(self, script_id: str, task_id: str, status: str, reason: str = "") -> None:
        def apply(progress: dict) -> None:
            for phase in progress.get("phases", []):
                for task in phase.get("tasks", []):
                    if task.get("id") == task_id:
                        task["status"] = status
                        if reason:
                            task["reason"] = reason
                        else:
                            task.pop("reason", None)
                        return

        self.mutate(script_id, apply)

    def snapshot(self, script_id: str) -> dict | None:
        with self._lock:
            progress = self._progress.get(script_id)
            return deepcopy(progress) if progress else None

    def mark_complete(self, script_id: str) -> None:
        self.mutate(script_id, lambda progress: progress.update(isComplete=True))

    def complete_if_all(self, script_id: str, accepted: set[str]) -> bool:
        def all_done(progress: dict) -> bool:
            return all(
                task.get("status") in accepted
                for phase in progress.get("phases", [])
                for task in phase.get("tasks", [])
            )

        with self._lock:
            progress = self._progress.get(script_id)
            complete = bool(progress) and all_done(progress)
            if complete and progress:
                progress["isComplete"] = True
            return complete

    def publish(self, script_id: str) -> None:
        with self._lock:
            thread_id = self._threads.get(script_id)
            snapshot = deepcopy(self._progress.get(script_id))
        if thread_id:
            publish(thread_id, self.event_type, snapshot)

    def reset(self, script_id: str) -> None:
        with self._lock:
            self._progress.pop(script_id, None)
            self._threads.pop(script_id, None)


convert_progress_registry = WorkflowProgressRegistry("convert_progress")
asset_progress_registry = WorkflowProgressRegistry("asset_progress")
