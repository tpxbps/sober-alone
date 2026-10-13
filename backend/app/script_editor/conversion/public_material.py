"""Only public inputs enter shared public outputs; truth remains isolated."""

from pydantic import BaseModel, Field

from app.script_editor.conversion.cache import cached_output
from app.script_editor.conversion.contracts import ScriptMetadata
from app.script_editor.conversion.disclosure import (
    PublicCharacter,
    PublicScenes,
    audience_material,
    invoke,
)


class PublicBundle(ScriptMetadata, PublicScenes):
    pass


class PublicRole(PublicCharacter):
    character_id: str


class PublicRoles(BaseModel):
    characters: list[PublicRole] = Field(min_length=1, max_length=4)


async def public_bundle(llm, state):
    material = {"标题": state.get("script_title", ""), **audience_material(state)}
    return await cached_output(
        state,
        "public_bundle",
        PublicBundle,
        material,
        lambda: invoke(
            llm,
            PublicBundle,
            "只使用开局公开材料生成剧本概述（100至200字）、标签、详情介绍，及简短的开场、总结邀请、投票提示。"
            "不补写真相、秘密、玩法教程或替玩家推理。所有字段必须有内容。",
            material,
            validate=validate_public_bundle,
        ),
    )


def validate_public_bundle(value):
    if any(not getattr(value, field).strip() for field in PublicBundle.model_fields):
        raise ValueError("公开介绍和主持文案不能为空")


async def public_character(llm, state, character, prompt):
    characters = state["disclosure_plan"]["characters"]
    index = next(
        i for i, c in enumerate(characters) if c["character_id"] == character["character_id"]
    )
    group = characters[index // 4 * 4 : index // 4 * 4 + 4]
    identities = [
        {k: c.get(k) for k in ("character_id", "name", "gender", "age", "occupation")}
        for c in group
    ]
    expected = {c["character_id"] for c in group}
    material = {"角色": identities, **audience_material(state)}

    def validate(value):
        if (
            len(value.characters) != len(expected)
            or {c.character_id for c in value.characters} != expected
        ):
            raise ValueError("每个指定角色恰好返回一次，并保留原character_id")

    result = await cached_output(
        state,
        "public_roles:" + ":".join(sorted(expected)),
        PublicRoles,
        material,
        lambda: invoke(
            llm,
            PublicRoles,
            prompt + "\n为输入的全部角色分别生成公开选角简介、外貌及音色。"
            "每项约100至200字，只用公开材料，不能猜测秘密。",
            material,
            validate=validate,
        ),
    )
    return next(c for c in result.characters if c.character_id == character["character_id"])
