"""LangGraph workflow orchestration behind the script-editor HTTP façade."""

from __future__ import annotations

import uuid
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from app.api.schemas.script_editor import ResumeWorkflowRequest, StartWorkflowRequest
from app.script_editor.graph import get_script_gen_graph
from app.script_editor.prompts.defaults import DEFAULT_PROMPTS
from app.script_editor.state import INTERRUPT_STEPS, STEP_INIT, STEP_LABELS, ScriptGenState


class WorkflowNotFoundError(LookupError):
    pass


class ScriptEditorWorkflowService:
    """Owns graph configuration, interrupts and response serialization."""

    def __init__(self, graph=None):
        self.graph = graph or get_script_gen_graph()

    @staticmethod
    def config(thread_id: str, checkpoint_id: str | None = None) -> RunnableConfig:
        configurable: dict[str, Any] = {"thread_id": thread_id}
        if checkpoint_id is not None:
            configurable["checkpoint_id"] = checkpoint_id
        return cast(RunnableConfig, {"configurable": configurable})

    async def start(self, request: StartWorkflowRequest) -> dict[str, Any]:
        thread_id = str(uuid.uuid4())
        config = self.config(thread_id)
        initial_state: dict[str, Any] = {
            "user_idea": request.user_idea,
            "player_count": request.player_count,
            "difficulty": request.difficulty,
            "num_clue_rounds": request.num_clue_rounds,
        }
        if request.prompts:
            initial_state["prompts"] = request.prompts
        await self.graph.ainvoke(cast(ScriptGenState, initial_state), config)
        response = self._live_response(thread_id, self.graph.get_state(config))
        response.pop("is_complete", None)
        return response

    def get_state(self, thread_id: str) -> dict[str, Any]:
        snapshot = self.graph.get_state(self.config(thread_id))
        if not snapshot.values:
            raise WorkflowNotFoundError("工作流不存在")
        response = self._live_response(thread_id, snapshot)
        response.pop("script_id", None)
        response.pop("script_title", None)
        return response

    async def resume(self, thread_id: str, request: ResumeWorkflowRequest) -> dict[str, Any]:
        config = self.config(thread_id)
        resume_data: dict[str, Any] = {"action": request.action}
        for field in (
            "content",
            "characters",
            "character_scripts",
            "human_review",
            "game_data_sections",
        ):
            value = getattr(request, field)
            if value is not None:
                resume_data[field] = value

        if request.prompt is not None:
            snapshot = self.graph.get_state(config)
            prompts = dict(snapshot.values.get("prompts", {}))
            prompt_key = self.prompt_key_for_action(
                snapshot.values.get("current_step", ""), request.action
            )
            if prompt_key:
                prompts[prompt_key] = request.prompt
                self.graph.update_state(config, {"prompts": prompts})

        pre_state = self.graph.get_state(config)
        self._register_from_values(pre_state.values, thread_id)
        await self.graph.ainvoke(Command(resume=resume_data), config)
        response = self._live_response(thread_id, self.graph.get_state(config))
        response.pop("script_id", None)
        response.pop("script_title", None)
        return response

    def update_prompt(self, thread_id: str, step: str, prompt: str) -> dict[str, Any]:
        config = self.config(thread_id)
        snapshot = self.graph.get_state(config)
        prompts = dict(snapshot.values.get("prompts", {}))
        prompts[step] = prompt
        self.graph.update_state(config, {"prompts": prompts})
        return {"success": True, "message": f"提示词已更新: {step}"}

    def update_title(self, thread_id: str, title: str) -> dict[str, Any]:
        title = title.strip()
        if not title:
            raise ValueError("标题不能为空")
        self.graph.update_state(self.config(thread_id), {"script_title": title})
        return {"success": True, "script_title": title}

    @staticmethod
    def get_defaults() -> dict[str, Any]:
        return {"success": True, "prompts": DEFAULT_PROMPTS}

    @staticmethod
    def get_steps() -> dict[str, Any]:
        steps = [
            "generate_outline",
            "review_outline",
            "generate_first_draft",
            "review_first_draft",
            "review_by_llm",
            "generate_final_draft",
            "review_final",
            "convert_to_game_data",
            "review_game_data",
            "safety_check",
            "save_to_database",
            "generate_assets",
        ]
        return {
            "success": True,
            "steps": [
                {
                    "step": step,
                    "label": STEP_LABELS.get(step, step),
                    "needs_review": step in INTERRUPT_STEPS,
                }
                for step in steps
            ],
        }

    def get_history(self, thread_id: str) -> dict[str, Any]:
        checkpoints = []
        for state in self.graph.get_state_history(self.config(thread_id)):
            if not state.values:
                continue
            configurable = (
                state.config.get("configurable", {}) if isinstance(state.config, dict) else {}
            )
            checkpoints.append(
                {
                    "checkpoint_id": configurable.get("checkpoint_id", ""),
                    "current_step": state.values.get("current_step", ""),
                    "next": list(state.next),
                    "interrupt": self.extract_interrupt(state),
                    "timestamp": getattr(state, "created_at", None),
                    "state": self.serialize_state(state.values),
                }
            )
        return {"success": True, "checkpoints": checkpoints}

    def get_checkpoint(self, thread_id: str, checkpoint_id: str) -> dict[str, Any]:
        snapshot = self.graph.get_state(self.config(thread_id, checkpoint_id))
        if not snapshot.values:
            raise WorkflowNotFoundError("检查点不存在")
        return {
            "success": True,
            "checkpoint_id": checkpoint_id,
            "current_step": snapshot.values.get("current_step", ""),
            "interrupt": self.extract_interrupt(snapshot),
            "state": self.serialize_state(snapshot.values),
        }

    async def fork(
        self, thread_id: str, checkpoint_id: str, state_updates: dict | None = None
    ) -> dict[str, Any]:
        checkpoint_config = self.config(thread_id, checkpoint_id)
        if state_updates:
            self.graph.update_state(checkpoint_config, state_updates)
        snapshot = self.graph.get_state(checkpoint_config)
        if not snapshot.values:
            raise WorkflowNotFoundError("检查点不存在")
        current_step = snapshot.values.get("current_step", "")
        if current_step == STEP_INIT:
            return {
                "success": True,
                "thread_id": thread_id,
                "current_step": STEP_INIT,
                "is_complete": False,
                "interrupt": None,
                "state": self.serialize_state(snapshot.values),
            }

        target_interrupt = self.phase_interrupt_step(current_step)
        next_nodes = list(snapshot.next) if snapshot.next else []
        if not target_interrupt or target_interrupt in next_nodes:
            await self.graph.ainvoke(None, checkpoint_config)
        else:
            matching = next(
                (
                    state
                    for state in self.graph.get_state_history(self.config(thread_id))
                    if target_interrupt in list(state.next or [])
                ),
                None,
            )
            await self.graph.ainvoke(None, matching.config if matching else checkpoint_config)
        response = self._live_response(thread_id, self.graph.get_state(self.config(thread_id)))
        response.pop("script_id", None)
        response.pop("script_title", None)
        return response

    def _live_response(self, thread_id: str, snapshot) -> dict[str, Any]:
        values = snapshot.values
        interrupt = self.extract_interrupt(snapshot)
        self._register_from_values(values, thread_id)
        has_error = bool(values.get("error_message"))
        return {
            "success": True,
            "thread_id": thread_id,
            "script_id": values.get("script_id", ""),
            "script_title": values.get("script_title", ""),
            "current_step": interrupt["step"] if interrupt else values.get("current_step", ""),
            "is_complete": snapshot.next == () and not has_error,
            "interrupt": interrupt,
            "state": self.serialize_state(values),
        }

    @staticmethod
    def _register_from_values(values: dict, thread_id: str) -> None:
        script_id = values.get("script_id", "")
        if not script_id:
            return
        ScriptEditorWorkflowService.register_script_thread(script_id, thread_id)

    @staticmethod
    def register_script_thread(script_id: str, thread_id: str) -> None:
        from app.script_editor.nodes.convert import register_script_thread as register_convert
        from app.script_editor.nodes.save import register_script_thread as register_assets

        register_convert(script_id, thread_id)
        register_assets(script_id, thread_id)

    @classmethod
    def extract_interrupt(cls, snapshot) -> dict | None:
        for task in getattr(snapshot, "tasks", ()):
            if task.interrupts and isinstance(task.interrupts[0].value, dict):
                value = task.interrupts[0].value
                return {
                    "step": value.get("step", ""),
                    "step_label": value.get("step_label", ""),
                    "generated_content": value.get("generated_content", ""),
                    "characters": value.get("characters", []),
                    "character_scripts": value.get("character_scripts", {}),
                    "review_opinion": value.get("review_opinion", ""),
                    "game_data_sections": value.get("game_data_sections", {}),
                    "prompt_used": value.get("prompt_used", ""),
                    "rejected": value.get("rejected", False),
                    "reason": value.get("reason", ""),
                }
        values = getattr(snapshot, "values", {})
        for node_name in getattr(snapshot, "next", ()):
            if node_name in INTERRUPT_STEPS:
                return cls.reconstruct_interrupt(node_name, values)
        current_step = values.get("current_step", "")
        if current_step in INTERRUPT_STEPS:
            return cls.reconstruct_interrupt(current_step, values)
        return None

    @staticmethod
    def reconstruct_interrupt(step: str, state: dict) -> dict[str, Any]:
        prompts = state.get("prompts", {})
        info = {
            "step": step,
            "step_label": STEP_LABELS.get(step, step),
            "generated_content": "",
            "characters": state.get("characters", []),
            "character_scripts": state.get("character_scripts", {}),
            "review_opinion": state.get("review_opinion", ""),
            "game_data_sections": state.get("game_data_sections", {}),
            "prompt_used": "",
            "rejected": False,
            "reason": "",
        }
        if step == "review_outline":
            info["generated_content"] = state.get("outline", "")
            info["prompt_used"] = prompts.get("generate_outline", "")
        elif step == "review_first_draft":
            info["generated_content"] = state.get("first_draft", "")
            info["prompt_used"] = prompts.get("generate_first_draft", "")
        elif step == "review_final":
            info["generated_content"] = state.get("final_draft", "")
            info["prompt_used"] = prompts.get("generate_final_draft", "")
        elif step == "review_game_data":
            info["prompt_used"] = prompts.get("convert_to_game_data", "")
        elif step == "safety_check":
            info["rejected"] = not state.get("safety_passed", False)
        return info

    @staticmethod
    def serialize_state(values: dict) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "script_title": "",
            "script_id": "",
            "user_idea": "",
            "player_count": 4,
            "difficulty": 1,
            "num_clue_rounds": 2,
            "outline": "",
            "characters": [],
            "first_draft": "",
            "review_opinion": "",
            "final_draft": "",
            "character_scripts": {},
            "game_data_sections": {},
            "prompts": {},
            "cover_image_url": "",
            "character_avatars": {},
            "error_message": "",
            "safety_passed": False,
            "safety_rejection_reason": "",
        }
        return {key: values.get(key, default) for key, default in defaults.items()}

    @staticmethod
    def prompt_key_for_action(current_step: str, action: str) -> str | None:
        regenerate = {
            "review_outline": "generate_outline",
            "review_first_draft": "generate_first_draft",
            "review_final": "generate_final_draft",
            "review_game_data": "convert_to_game_data",
        }
        confirm = {
            "review_outline": "generate_first_draft",
            "review_first_draft": None,
            "review_final": "convert_to_game_data",
            "review_game_data": None,
        }
        return regenerate.get(current_step) if action == "regenerate" else confirm.get(current_step)

    @staticmethod
    def phase_interrupt_step(current_step: str) -> str | None:
        mapping = {
            STEP_INIT: None,
            "generate_outline": "review_outline",
            "review_outline": "review_outline",
            "generate_first_draft": "review_first_draft",
            "review_first_draft": "review_first_draft",
            "review_by_llm": "review_final",
            "generate_final_draft": "review_final",
            "review_final": "review_final",
            "convert_to_game_data": "review_game_data",
            "review_game_data": "review_game_data",
            "safety_check": "safety_check",
        }
        return mapping.get(current_step)
