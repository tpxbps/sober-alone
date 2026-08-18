"""
Game API routes
游戏相关API端点
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.game_service import GameService

router = APIRouter(prefix="/game", tags=["game"])


# ============== Request/Response Models ==============


class LLMConfig(BaseModel):
    """单个角色的LLM配置"""

    provider: str | None = Field(
        None,
        description="LLM提供商 (stepfun/deepseek/alibaba/bytedance)，为空时使用默认提供商",
    )
    model: str | None = Field(None, description="模型名称，为空时使用默认值")


class GameCreateRequest(BaseModel):
    """创建游戏请求"""

    script_id: str = Field(..., description="剧本ID")
    human_character_id: str = Field(..., description="真人玩家选择的角色ID")
    llm_configs: dict[str, LLMConfig] | None = Field(
        None,
        description="可选的角色LLM配置，格式: {character_id: {provider: str, model: str}}",
    )


class GameCreateResponse(BaseModel):
    """创建游戏响应"""

    success: bool
    session_id: str | None = None
    status: str | None = None
    current_stage: str | None = None
    current_speaker: str | None = None
    characters: list[dict[str, Any]] | None = None
    llm_configs: dict[str, dict[str, str | None]] | None = None
    error: str | None = None


class SpeechRequest(BaseModel):
    """发言请求"""

    content: str = Field(..., min_length=1, max_length=3000, description="发言内容")


class AdvanceRequest(BaseModel):
    """推进流程请求"""

    action: str = Field(default="next", description="推进动作")


class VoteRequest(BaseModel):
    """投票请求（真人玩家）"""

    suspect_id: str = Field(..., description="投票的嫌疑人角色ID")
    suspect_name: str = Field(..., description="投票的嫌疑人名称")
    reasoning: str = Field(default="", max_length=1000, description="投票理由（可选）")


class TTSGenerateRequest(BaseModel):
    """TTS 音频生成请求"""

    record_id: int = Field(..., description="游戏记录 ID")


# ============== API Endpoints ==============


@router.post("/create", response_model=GameCreateResponse)
async def create_game(request: GameCreateRequest, db: AsyncSession = Depends(get_db)):
    """
    创建新游戏对局

    - **script_id**: 剧本ID
    - **human_character_id**: 真人玩家选择扮演的角色ID
    - **llm_configs**: 可选的角色LLM配置，格式: {character_id: {provider: str, model: str}}
    """
    game_service = GameService(db)

    # 转换llm_configs格式
    llm_configs_dict = None
    if request.llm_configs:
        llm_configs_dict = {
            char_id: {"provider": config.provider, "model": config.model}
            for char_id, config in request.llm_configs.items()
        }

    result = await game_service.create_game(
        script_id=request.script_id,
        human_character_id=request.human_character_id,
        llm_configs=llm_configs_dict,
    )
    return GameCreateResponse(**result)


@router.get("/{session_id}/state")
async def get_game_state(session_id: str, db: AsyncSession = Depends(get_db)):
    """
    获取游戏状态

    - **session_id**: 游戏会话ID
    """
    game_service = GameService(db)
    result = await game_service.get_game_state(session_id)

    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "游戏会话不存在"))

    return result


@router.post("/{session_id}/speech")
async def player_speech(
    session_id: str, request: SpeechRequest, db: AsyncSession = Depends(get_db)
):
    """
    真人玩家发言（流式 - SSE格式）

    返回SSE格式的流式数据:
    - speech_recorded: 发言已记录
    - thinking: AI正在反应（带角色名提示）
    - reactions_done: 所有反应完成
    - done: 流结束，包含下一位发言者信息

    - **session_id**: 游戏会话ID
    - **content**: 发言内容
    """
    game_service = GameService(db)

    async def generate():
        async for chunk in game_service.process_human_speech_stream(
            session_id=session_id, content=request.content
        ):
            yield chunk

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/{session_id}/ai-speech/{character_id}")
async def ai_speech(
    session_id: str,
    character_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    AI玩家发言（流式 - SSE格式）

    让指定的AI基于当前游戏stage生成发言内容

    返回SSE格式的流式数据，事件类型包括:
    - token: LLM生成的文本片段
    - tool_call: 工具调用
    - tool_result: 工具执行结果
    - progress: Agent进度更新
    - done: 流结束标记

    - **session_id**: 游戏会话ID
    - **character_id**: AI角色ID
    - **tts**: 是否启用TTS语音合成（默认false）
    """
    game_service = GameService(db)

    async def generate():
        async for chunk in game_service.process_ai_speech_stream(session_id, character_id):
            yield chunk

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/{session_id}/advance")
async def advance_stage(
    session_id: str,
    request: AdvanceRequest = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """
    推进游戏流程

    将游戏推进到下一个阶段

    - **session_id**: 游戏会话ID
    - **action**: 推进动作（默认为"next"）
    """
    game_service = GameService(db)
    result = await game_service.advance_stage(session_id)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "推进失败"))

    return result


@router.post("/{session_id}/vote")
async def submit_vote(session_id: str, request: VoteRequest, db: AsyncSession = Depends(get_db)):
    """
    提交真人玩家投票

    真人玩家提交最终投票，理由可选。
    前端直接提供选项，接口接收真人玩家认为的最终结果id+名称+可选理由。

    - **session_id**: 游戏会话ID
    - **suspect_id**: 投票的嫌疑人角色ID
    - **suspect_name**: 投票的嫌疑人名称
    - **reasoning**: 投票理由（可选）
    """
    game_service = GameService(db)
    result = await game_service.submit_vote(
        session_id=session_id,
        suspect_id=request.suspect_id,
        suspect_name=request.suspect_name,
        reasoning=request.reasoning,
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "投票失败"))

    return result


@router.post("/{session_id}/finalize-voting")
async def finalize_voting(session_id: str, db: AsyncSession = Depends(get_db)):
    """
    完成投票并推进到复盘阶段

    收集所有投票结果，判断最终结果，将游戏推进到复盘阶段。

    - **session_id**: 游戏会话ID
    """
    game_service = GameService(db)
    result = await game_service.finalize_voting(session_id)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "完成投票失败"))

    return result


@router.get("/{session_id}/records")
async def get_game_records(session_id: str, limit: int = 50, db: AsyncSession = Depends(get_db)):
    """
    获取游戏记录

    获取游戏中的所有对话记录

    - **session_id**: 游戏会话ID
    - **limit**: 返回记录数量（默认50）
    """
    game_service = GameService(db)
    records = await game_service.get_game_records(session_id, limit)

    return {
        "success": True,
        "session_id": session_id,
        "records": records,
        "count": len(records),
    }


@router.post("/{session_id}/abandon")
async def abandon_session(session_id: str, db: AsyncSession = Depends(get_db)):
    """
    放弃游戏会话（用于用户中途退出)

    不管游戏状态如何，都会清理后端内存中的资源。
    用于前端检测到用户点击"退出"按钮时调用。

    - **session_id**: 游戏会话ID
    """
    game_service = GameService(db)
    result = await game_service.abandon_session(session_id)
    return result


@router.post("/{session_id}/end")
async def end_game(session_id: str, db: AsyncSession = Depends(get_db)):
    """
    结束游戏

    在复盘阶段后调用，清理游戏资源并标记游戏结束。
    注意：真相（full_truth）已在 /finalize-voting 的 review_message 中返回。

    - **session_id**: 游戏会话ID
    """
    game_service = GameService(db)
    result = await game_service.end_game(session_id)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "结束失败"))

    return result


# ============== TTS API ==============


@router.post("/{session_id}/tts/stream")
async def stream_tts_audio(
    session_id: str, request: TTSGenerateRequest, db: AsyncSession = Depends(get_db)
):
    """
    流式 TTS 音频生成（SSE）

    通过 StepFun WebSocket 流式生成语音，通过 SSE 实时推送给前端。
    不落盘，前端负责缓存。

    SSE 事件类型:
    - audio_delta: 音频块（base64 编码的 MP3）
    - audio_done: 生成完成，data.audio 包含完整音频
    - error: 错误

    - **session_id**: 游戏会话 ID
    - **record_id**: 游戏记录 ID
    """
    from sqlalchemy import select
    from sqlalchemy import text as sql_text

    from app.db.models import GameRecord
    from app.services.streaming_tts import StreamingTTSSession

    # 获取记录
    result = await db.execute(select(GameRecord).where(GameRecord.id == request.record_id))
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    # 校验 record 属于当前 session
    if record.session_id != session_id:
        raise HTTPException(status_code=403, detail="记录不属于此会话")

    if not record.raw_content:
        raise HTTPException(status_code=400, detail="记录无文本内容")

    # 获取角色 voice_id（根据性别选择默认值）
    default_male_voice = "cixingnansheng"
    default_female_voice = "lengyanyujie"
    voice_id = default_male_voice
    if record.speaker_character_id:
        char_result = await db.execute(
            sql_text("SELECT voice_id, gender FROM characters WHERE character_id = :cid"),
            {"cid": record.speaker_character_id},
        )
        char_row = char_result.fetchone()
        if char_row and char_row[0]:
            voice_id = char_row[0]
        elif char_row and char_row[1]:
            gender = str(char_row[1]).strip()
            if gender in ("女", "female", "F", "f"):
                voice_id = default_female_voice

    import json

    async def generate():
        tts = StreamingTTSSession()
        try:
            connected = await tts.connect(voice_id)
            if not connected:
                yield f"data: {json.dumps({'type': 'error', 'message': 'TTS 连接失败'})}\n\n"
                return

            # 发送完整文本
            text = record.raw_content or ""
            if not text:
                yield f"data: {json.dumps({'type': 'error', 'message': '文本内容为空'})}\n\n"
                return
            await tts.send_text(text)
            await tts.flush()
            await tts.finish()

            # 流式转发音频块
            complete_audio_parts = []
            async for chunk in tts.receive_audio():
                yield f"data: {json.dumps({'type': 'audio_delta', 'audio': chunk['audio'], 'duration': chunk.get('duration', 0)}, ensure_ascii=False)}\n\n"
                complete_audio_parts.append(chunk["audio"])

            # 发送完成事件
            yield f"data: {json.dumps({'type': 'audio_done'})}\n\n"

        except Exception as e:
            import logging

            logging.getLogger(__name__).error(f"TTS stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            await tts.close()

    return StreamingResponse(generate(), media_type="text/event-stream")


# ============== Script API ==============


@router.get("/scripts")
async def list_scripts(db: AsyncSession = Depends(get_db)):
    """
    获取剧本列表

    返回所有可用的剧本
    """
    from sqlalchemy import text

    result = await db.execute(
        text(
            "SELECT script_id, title, overview, tags, difficulty, player_count, cover_image_url, is_ai_generated, estimated_duration FROM scripts"
        )
    )
    scripts = result.fetchall()

    return {
        "success": True,
        "scripts": [
            {
                "script_id": row[0],
                "title": row[1],
                "overview": row[2],
                "tags": row[3],
                "difficulty": row[4],
                "player_count": row[5],
                "cover_image_url": row[6],
                "is_ai_generated": bool(row[7]) if row[7] is not None else False,
                "estimated_duration": row[8] if row[8] else 0,
            }
            for row in scripts
        ],
    }


@router.get("/scripts/{script_id}/characters")
async def get_script_characters(script_id: str, db: AsyncSession = Depends(get_db)):
    """
    获取剧本角色列表

    返回指定剧本的所有角色信息（模糊版，不包含关键秘密）

    - **script_id**: 剧本ID
    """
    from sqlalchemy import text

    result = await db.execute(
        text(
            """
            SELECT character_id, name, gender, age, occupation, profile, avatar_url, voice_id
            FROM characters
            WHERE script_id = :script_id
        """
        ),
        {"script_id": script_id},
    )
    characters = result.fetchall()

    return {
        "success": True,
        "script_id": script_id,
        "characters": [
            {
                "character_id": row[0],
                "name": row[1],
                "gender": row[2],
                "age": row[3],
                "occupation": row[4],
                "profile": row[5],
                "avatar_url": row[6],
                "voice_id": row[7],
            }
            for row in characters
        ],
    }
