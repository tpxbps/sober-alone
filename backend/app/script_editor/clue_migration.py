"""Resumable legacy clue conversion and clue-only TTS regeneration."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import settings
from app.core.llm_factory import create_llm
from app.db.models import Character, Script
from app.db.session import AsyncSessionLocal
from app.game.clues import CLUE_SCHEMA_VERSION, derive_game_process, normalize_clue_stages
from app.script_editor.services.tts_gen import generate_script_tts


class ConvertedClueItem(BaseModel):
    summary: str = Field(min_length=1)
    content: str = Field(min_length=1)


class ConvertedClueStage(BaseModel):
    stage: int = Field(ge=1)
    overview: str
    items: list[ConvertedClueItem] = Field(min_length=1)
    free_discussion_notice: str = ""


class ConvertedClues(BaseModel):
    stages: list[ConvertedClueStage] = Field(min_length=1)


class ConversionAudit(BaseModel):
    passed: bool
    coverage_notes: list[str] = Field(default_factory=list)
    omissions: list[str] = Field(default_factory=list)
    invented_facts: list[str] = Field(default_factory=list)


def _legacy_payload(script: Script) -> list[dict]:
    result = []
    stage = 0
    for process in script.game_full_process or []:
        if process.get("type") != "advancement":
            continue
        stage += 1
        children = process.get("children") or []
        clue_text = children[0].get("system_notice", "") if children else ""
        clue_parts = re.split(r"\n\s*\n(?=请)", str(clue_text).strip(), maxsplit=1)
        embedded_discussion = clue_parts[1].strip() if len(clue_parts) > 1 else ""
        explicit_discussion = (
            str(children[1].get("system_notice", "")) if len(children) > 1 else ""
        ).strip()
        result.append(
            {
                "stage": stage,
                "clue_text": clue_parts[0].strip(),
                "free_discussion_notice": "\n\n".join(
                    item for item in (embedded_discussion, explicit_discussion) if item
                ),
            }
        )
    return result


def _digest(payload: list[dict]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _load_manifest(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"scripts": {}}
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "scripts": {}}


def _save_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


async def _convert(script: Script, source: list[dict]) -> tuple[list[dict], dict]:
    llm = create_llm(
        model="deepseek-v4-flash",
        temperature=0,
        timeout=180,
        max_retries=2,
        disable_thinking=True,
    )
    converter = llm.with_structured_output(ConvertedClues)
    prompt = (
        "把下面每一轮旧系统线索拆成 overview 和若干独立线索项。"
        "必须逐轮处理，stage 原样保留；只能拆分、摘取和概括原文，禁止增加、删除、"
        "改写事实或把讨论提示混入线索。summary 简短明确，content 保留支撑该线索的完整细节。"
        "不要生成 ID。\n\n" + json.dumps(source, ensure_ascii=False, indent=2)
    )
    converted = await converter.ainvoke(
        [
            SystemMessage(content="你是剧本数据迁移器，事实保真高于文采。"),
            HumanMessage(content=prompt),
        ]
    )
    converted_data = ConvertedClues.model_validate(converted).model_dump()
    if len(converted_data["stages"]) != len(source):
        raise ValueError("结构化结果的线索轮次数与原文不一致")
    for stage, original in zip(converted_data["stages"], source, strict=True):
        stage["stage"] = original["stage"]
        # Discussion guidance is deterministic legacy data, not model-generated content.
        stage["free_discussion_notice"] = original["free_discussion_notice"]
    normalized = normalize_clue_stages(
        converted_data["stages"],
        script_id=script.script_id,
        game_full_process=script.game_full_process or [],
    )

    auditor = llm.with_structured_output(ConversionAudit)
    audit_prompt = (
        "逐轮对比原文与结构化结果。只有所有事实均被覆盖、没有新增事实、轮次和讨论提示"
        "均正确时 passed 才能为 true。\n原文：\n"
        + json.dumps(source, ensure_ascii=False, indent=2)
        + "\n结果：\n"
        + json.dumps(normalized, ensure_ascii=False, indent=2)
    )
    audit = await auditor.ainvoke(
        [SystemMessage(content="你是严格的数据迁移审计员。"), HumanMessage(content=audit_prompt)]
    )
    audit_data = ConversionAudit.model_validate(audit).model_dump()
    if not audit_data["passed"] or audit_data["omissions"] or audit_data["invented_facts"]:
        raise ValueError(f"覆盖审查未通过: {json.dumps(audit_data, ensure_ascii=False)}")
    return normalized, audit_data


async def migrate_legacy_clues(
    *,
    apply: bool = False,
    script_ids: list[str] | None = None,
    manifest_path: Path | None = None,
    force: bool = False,
) -> None:
    """Convert old clue messages. Dry-run is the mandatory default."""

    manifest_path = manifest_path or (
        settings.local_data_dir / "migrations" / "clue-conversion-manifest.json"
    )
    manifest = _load_manifest(manifest_path)
    entries = manifest.setdefault("scripts", {})
    had_failures = False

    async with AsyncSessionLocal() as db:
        query = select(Script).order_by(Script.created_at, Script.script_id)
        if script_ids:
            query = query.where(Script.script_id.in_(script_ids))
        scripts = list(await db.scalars(query))
        for script in scripts:
            script_id = script.script_id
            script_title = script.title
            game_process = list(script.game_full_process or [])
            if (
                not force
                and script.clue_schema_version >= CLUE_SCHEMA_VERSION
                and script.clue_stages
            ):
                print(f"SKIP {script_id}: already structured")
                continue
            source = _legacy_payload(script)
            if not source or any(not item["clue_text"].strip() for item in source):
                print(f"SKIP {script_id}: no complete legacy clue rounds")
                continue
            source_hash = _digest(source)
            cached = entries.get(script_id, {})
            try:
                if (
                    cached.get("input_sha256") == source_hash
                    and cached.get("status") in {"validated", "applied"}
                    and cached.get("result")
                ):
                    clues = normalize_clue_stages(
                        cached["result"],
                        script_id=script_id,
                        game_full_process=game_process,
                    )
                    audit = cached.get("audit", {})
                else:
                    clues, audit = await _convert(script, source)
                entries[script_id] = {
                    "input_sha256": source_hash,
                    "status": "validated",
                    "result": clues,
                    "audit": audit,
                    "error": "",
                    "updated_at": datetime.now().isoformat(),
                }
                _save_manifest(manifest_path, manifest)
                if apply:
                    next_process = derive_game_process(game_process, clues)
                    if script.clue_stages != clues or script.game_full_process != next_process:
                        script.content_fingerprint = None
                    script.clue_stages = clues
                    script.clue_schema_version = CLUE_SCHEMA_VERSION
                    script.game_full_process = next_process
                    await db.commit()
                    entries[script_id]["status"] = "applied"
                    _save_manifest(manifest_path, manifest)
                print(f"{'APPLY' if apply else 'VALID'} {script_id} {script_title}")
            except Exception as error:
                await db.rollback()
                had_failures = True
                entries[script_id] = {
                    "input_sha256": source_hash,
                    "status": "failed",
                    "result": cached.get("result"),
                    "audit": cached.get("audit"),
                    "error": str(error),
                    "updated_at": datetime.now().isoformat(),
                }
                _save_manifest(manifest_path, manifest)
                print(f"FAIL {script_id}: {error}")
    if had_failures:
        raise RuntimeError("部分剧本转换失败；数据库未写入失败项，请查看迁移 manifest")


def backup_database(database_path: Path) -> Path:
    if not database_path.is_file():
        raise FileNotFoundError(f"Database not found: {database_path}")
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = database_path.with_name(f"{database_path.name}.before-clues-{timestamp}.bak")
    with sqlite3.connect(database_path) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    return backup


async def regenerate_clue_tts(script_ids: list[str] | None = None) -> None:
    if not settings.MIMO_API_KEY:
        raise RuntimeError("MIMO_API_KEY 未配置")
    async with AsyncSessionLocal() as db:
        query = select(Script).order_by(Script.created_at, Script.script_id)
        if script_ids:
            query = query.where(Script.script_id.in_(script_ids))
        scripts = list(await db.scalars(query))
        for script in scripts:
            if script.clue_schema_version < CLUE_SCHEMA_VERSION or not script.clue_stages:
                print(f"SKIP {script.script_id}: clues not migrated")
                continue
            audio_dir = settings.audio_dir / "scripts" / script.script_id / "system_messages"
            if audio_dir.exists():
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                backup = audio_dir.with_name(f"system_messages.before-clues-{timestamp}")
                shutil.copytree(audio_dir, backup)
            characters = list(
                await db.scalars(select(Character).where(Character.script_id == script.script_id))
            )
            task_ids: set[str] = set()
            for index, process in enumerate(script.game_full_process or []):
                if process.get("type") == "advancement":
                    task_ids.add(f"tts_sys_{index}_0")
            result = await generate_script_tts(
                script_id=script.script_id,
                character_scripts={},
                characters=[
                    {
                        "character_id": item.character_id,
                        "name": item.name,
                        "gender": item.gender,
                    }
                    for item in characters
                ],
                game_full_process=script.game_full_process or [],
                clue_stages=script.clue_stages or [],
                selected_task_ids=task_ids,
                force=True,
            )
            expected = len(task_ids)
            generated = len(result.get("system_messages", {}))
            if generated != expected:
                raise RuntimeError(
                    f"{script.script_id} clue TTS incomplete: {generated}/{expected}"
                )
            print(f"TTS OK {script.script_id}: {generated} clue stages")
