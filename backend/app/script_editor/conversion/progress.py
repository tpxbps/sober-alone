"""Thread-safe conversion progress facade."""

from app.script_editor.services.progress_registry import convert_progress_registry


def register_script_thread(script_id: str, thread_id: str):
    convert_progress_registry.register_thread(script_id, thread_id)


def _init_convert_progress(
    script_id: str,
    characters: list[dict],
    player_count: int,
    previous: dict | None = None,
):
    need_discovery = len(characters) == 0

    char_tasks = []
    if need_discovery:
        char_tasks.append(
            {
                "id": "disclosure",
                "label": f"整理剧情与信息范围（{player_count}人）",
                "status": "pending",
            }
        )
    for i, c in enumerate(characters):
        char_tasks.append(
            {
                "id": f"char_{c.get('character_id') or c.get('name', str(i))}",
                "label": f"{c.get('name', '?')}个人本",
                "status": "pending",
            }
        )

    char_label = f"角色数据生成（{len(characters)}人）" if characters else "整理剧情与信息范围"

    phases = [
        {
            "id": "game_flow",
            "label": "分轮线索",
            "tech": "LLM",
            "tasks": [
                {
                    "id": "game_flow",
                    "label": "整理各轮线索",
                    "status": "pending",
                },
            ],
        },
        {
            "id": "game_scenes",
            "label": "真相与结局",
            "tech": "LLM",
            "tasks": [
                {
                    "id": "game_scenes",
                    "label": "整理完整真相与揭晓",
                    "status": "pending",
                },
            ],
        },
        {
            "id": "metadata",
            "label": "公开介绍与主持流程",
            "tech": "LLM",
            "tasks": [
                {
                    "id": "metadata",
                    "label": "编排公开介绍、开场与主持提示",
                    "status": "pending",
                },
            ],
        },
        {
            "id": "characters",
            "label": char_label,
            "tech": "LLM",
            "tasks": char_tasks,
        },
    ]
    phases = [phases[3], phases[2], phases[0], phases[1]]
    if previous:
        old = {t["id"]: t for p in previous.get("phases", []) for t in p.get("tasks", [])}
        for phase in phases:
            for task in phase["tasks"]:
                if task["id"] in old:
                    task.update(
                        {k: v for k, v in old[task["id"]].items() if k in {"status", "reason"}}
                    )
        for phase in previous.get("phases", []):
            for task in phase.get("tasks", []):
                if task["id"].startswith("char_"):
                    phases[0]["tasks"].append(dict(task))
    convert_progress_registry.init(script_id, phases)
    _publish_convert_progress(script_id)


def _add_character_tasks(script_id: str, characters: list[dict]):
    """角色发现成功后，动态添加角色任务到进度树"""

    def add_tasks(progress: dict) -> None:
        for phase in progress["phases"]:
            if phase["id"] == "characters":
                phase["label"] = f"角色个人本（{len(characters)}人）"
                for i, c in enumerate(characters):
                    task_id = f"char_{c.get('character_id') or c.get('name', str(i))}"
                    if any(t["id"] == task_id for t in phase["tasks"]):
                        continue
                    phase["tasks"].append(
                        {
                            "id": task_id,
                            "label": f"{c.get('name', '?')}个人本",
                            "status": "pending",
                        }
                    )
                break

    convert_progress_registry.mutate(script_id, add_tasks)
    _publish_convert_progress(script_id)


def task_failure_reason(error: Exception) -> str:
    from app.script_editor.llm import StructuredOutputTruncated

    if isinstance(error, StructuredOutputTruncated):
        return "本次内容过长，尚未完整返回；已完成的部分会保留。"
    if isinstance(error, ValueError):
        return "部分内容或信息范围还需整理；重试会继续修复未通过的部分。"
    return "生成服务暂时未完成请求，请稍后重试。"


def _update_convert_task(script_id: str, task_id: str, status: str, reason: str = ""):
    # Internal batches and cast discovery are one logical creator-facing task.
    if task_id.startswith("facts_") or task_id == "discover_chars":
        return
    if status == "failed" and not reason:
        previous = convert_progress_registry.snapshot(script_id) or {}
        reason = next(
            (
                task.get("reason", "")
                for phase in previous.get("phases", [])
                for task in phase.get("tasks", [])
                if task.get("id") == task_id
            ),
            "",
        )
        reason = reason or "本次内容尚未完整生成，请重试。"
    convert_progress_registry.update_task(script_id, task_id, status, reason)
    _publish_convert_progress(script_id)


def _mark_convert_complete(script_id: str):
    convert_progress_registry.mark_complete(script_id)
    _publish_convert_progress(script_id)


def _publish_convert_progress(script_id: str):
    convert_progress_registry.publish(script_id)


def get_convert_progress(script_id: str) -> dict | None:
    return convert_progress_registry.snapshot(script_id)


def reset_convert_progress(script_id: str):
    convert_progress_registry.reset(script_id)


def add_disclosure_task(script_id: str, task_id: str, label: str):
    # Kept as a compatibility hook; fragment identifiers belong in diagnostics.
    pass
