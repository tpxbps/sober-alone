"""Thread-safe conversion progress facade."""

from app.script_editor.services.progress_registry import convert_progress_registry


def register_script_thread(script_id: str, thread_id: str):
    convert_progress_registry.register_thread(script_id, thread_id)


def _init_convert_progress(
    script_id: str,
    characters: list[dict],
    player_count: int,
):
    need_discovery = len(characters) == 0

    char_tasks = []
    if need_discovery:
        char_tasks.append(
            {
                "id": "discover_chars",
                "label": f"从终稿中识别 {player_count} 个角色",
                "status": "pending",
            }
        )
    for i, c in enumerate(characters):
        char_tasks.append(
            {
                "id": f"char_{c.get('name', str(i))}",
                "label": f"{c.get('name', '?')} 完整数据",
                "status": "pending",
            }
        )

    char_label = (
        f"角色数据生成（{len(characters)}人）"
        if characters
        else f"角色识别与数据生成（{player_count}人）"
    )

    phases = [
        {
            "id": "game_flow",
            "label": "线索阶段数据",
            "tech": "LLM",
            "tasks": [
                {
                    "id": "game_flow",
                    "label": "生成线索阶段系统消息",
                    "status": "pending",
                },
            ],
        },
        {
            "id": "game_scenes",
            "label": "开场与真相",
            "tech": "LLM",
            "tasks": [
                {
                    "id": "game_scenes",
                    "label": "生成开场、投票、真相消息",
                    "status": "pending",
                },
            ],
        },
        {
            "id": "metadata",
            "label": "剧本元数据",
            "tech": "LLM",
            "tasks": [
                {
                    "id": "metadata",
                    "label": "生成概述、标签、描述",
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
    convert_progress_registry.init(script_id, phases)
    _publish_convert_progress(script_id)


def _add_character_tasks(script_id: str, characters: list[dict]):
    """角色发现成功后，动态添加角色任务到进度树"""

    def add_tasks(progress: dict) -> None:
        for phase in progress["phases"]:
            if phase["id"] == "characters":
                phase["label"] = f"角色数据生成（{len(characters)}人）"
                for i, c in enumerate(characters):
                    phase["tasks"].append(
                        {
                            "id": f"char_{c.get('name', str(i))}",
                            "label": f"{c.get('name', '?')} 完整数据",
                            "status": "pending",
                        }
                    )
                break

    convert_progress_registry.mutate(script_id, add_tasks)
    _publish_convert_progress(script_id)


def _update_convert_task(script_id: str, task_id: str, status: str):
    convert_progress_registry.update_task(script_id, task_id, status)
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
