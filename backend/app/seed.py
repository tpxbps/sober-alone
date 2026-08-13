"""Deterministic, text-only sample data for a fresh local installation."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Character, Script

SAMPLE_SCRIPT_ID = "sample-fog-harbor-echo-v1"


def _game_process() -> list[dict]:
    return [
        {
            "type": "initial",
            "stage_title": "雾港夜航",
            "system_notice": (
                "凌晨零点，雾港旧灯塔的警报忽然响起。港务档案员顾闻舟倒在潮汐机房，"
                "记录着走私航线的蓝色账册不翼而飞。暴雨封住了离港公路，在巡逻艇靠岸前，"
                "请四位留在灯塔的人依次说明身份与今晚的行踪。"
            ),
        },
        {
            "type": "advancement",
            "children": [
                {
                    "stage_title": "第一轮·机房痕迹",
                    "system_notice": (
                        "第一轮线索：机房门锁没有撬痕；死者手中攥着一截沾有蓝漆的麻绳；"
                        "备用发电机在23:36至23:44停机；窗沿发现少量新鲜海盐，但窗户从内侧插住。"
                    ),
                },
                {
                    "stage_title": "第一轮·自由讨论",
                    "system_notice": "请围绕停电、蓝漆麻绳和密闭窗户交换信息。每人最多发言两次。",
                },
            ],
        },
        {
            "type": "advancement",
            "children": [
                {
                    "stage_title": "第二轮·遗失账册",
                    "system_notice": (
                        "第二轮线索：顾闻舟的怀表停在23:41；气象站录音里23:39出现三短一长的汽笛；"
                        "灯塔储物柜少了一把黄铜扳手；蓝色账册的封皮碎片藏在无线电台废纸篓中，"
                        "碎片背面写着‘不是船名，是潮位’。"
                    ),
                },
                {
                    "stage_title": "第二轮·自由讨论",
                    "system_notice": "所有关键线索已经公开。请核对时间线、动机与伪造的不在场证明。",
                },
            ],
        },
        {
            "type": "vote",
            "children": [
                {
                    "stage_title": "总结发言",
                    "system_notice": "请依次给出最终推理，并说明你认为谁拿走账册、谁导致顾闻舟死亡。",
                },
                {
                    "stage_title": "最终投票",
                    "system_notice": "总结结束。请投票指认应为顾闻舟之死负责的人。",
                },
            ],
        },
        {
            "type": "review",
            "stage_title": "真相复盘",
            "system_notice": (
                "真相：林岚发现蓝色账册记录的不是船名，而是利用潮位掩护的走私交接时间。"
                "她想带走账册交给调查记者，却被顾闻舟堵在机房。争执中她用黄铜扳手击中阀门，"
                "蒸汽泄压使顾闻舟跌倒撞伤；她误以为顾闻舟已死，借气象站预设汽笛制造自己在观测台的假象。"
                "顾闻舟仍有意识，用蓝漆麻绳和停在23:41的怀表留下指向维修浮标与时间线的线索。"
                "真正长期参与走私的是赵屿，但赵屿没有直接造成死亡。沈砚藏起部分无线电记录是为了保护家人，"
                "苏禾则因擅自进入机房而撒谎。林岚应为过失致死和藏匿账册负责。"
            ),
        },
    ]


CHARACTERS = [
    {
        "character_id": "f1000000-0000-4000-8000-000000000001",
        "name": "林岚",
        "gender": "女",
        "age": 31,
        "occupation": "气象观测员",
        "profile": "冷静克制，熟悉灯塔设备与港口气象信号。",
        "character_script_summary": "掌握气象站定时信号，声称案发时一直在观测台。",
        "character_script": (
            "你是林岚。你在蓝色账册里发现走私交接使用潮位数字编码，准备把账册交给记者。"
            "23:34你进入机房取走账册，被顾闻舟发现。争执中你挥动黄铜扳手，本想砸开卡住的泄压阀，"
            "却令蒸汽喷出，顾闻舟后退跌倒撞上金属台。你惊慌地拿走账册，把封皮碎片丢进无线电台废纸篓，"
            "并启动预设汽笛，伪装23:39仍在观测台。你不知道顾闻舟当时尚有意识。你的目标是隐藏直接冲突，"
            "但可以承认调查走私；不要捏造未写明的物证。"
        ),
        "system_prompt": (
            "你扮演林岚，气象观测员。你导致了致命事故并藏起账册。保持克制，优先解释自己调查走私的动机，"
            "在证据不足时隐瞒机房冲突；被明确指出汽笛可预设后，应逐步承认时间线矛盾。"
        ),
    },
    {
        "character_id": "f1000000-0000-4000-8000-000000000002",
        "name": "赵屿",
        "gender": "男",
        "age": 42,
        "occupation": "拖船船长",
        "profile": "熟悉潮汐与航道，为人强硬，右袖常沾维修浮标的蓝漆。",
        "character_script_summary": "与账册中的走私航线有关，但声称案发时在码头检查缆绳。",
        "character_script": (
            "你是赵屿。过去半年你收钱替人把未报关货物拖进雾港，顾闻舟用蓝色账册记录潮位与交接时间。"
            "你今晚23:20在维修浮标处更换蓝漆麻绳，23:32回到码头；停电后你去发电机房外查看，"
            "却怕暴露走私而没有进入。你看见林岚约23:45从无线电台方向出来，手里夹着深色册子。"
            "你没有杀顾闻舟，但蓝漆麻绳会让人怀疑你。你的目标是洗清命案嫌疑；可以在压力下承认走私，"
            "但不要把自己没看到的冲突说成事实。"
        ),
        "system_prompt": (
            "你扮演赵屿，拖船船长。说话直接、戒备心强。你参与走私但没有杀人。优先区分走私责任与命案责任，"
            "用自己看到林岚携带册子的事实推进推理。"
        ),
    },
    {
        "character_id": "f1000000-0000-4000-8000-000000000003",
        "name": "沈砚",
        "gender": "男",
        "age": 27,
        "occupation": "无线电维修员",
        "profile": "寡言细致，能读取无线电台与汽笛控制器的日志。",
        "character_script_summary": "删除过一段无线电记录，并发现汽笛可以预设。",
        "character_script": (
            "你是沈砚。你的哥哥欠走私团伙钱，你曾删除一段能暴露哥哥联络人的无线电记录。"
            "23:30你在无线电台检修，23:38发现气象站汽笛控制器存在一条预设指令，执行时间是23:39。"
            "23:43你听见机房方向金属落地声，赶到走廊时只看到苏禾从楼梯下方上来。"
            "后来你在废纸篓发现蓝色封皮碎片，因担心自己删记录的事暴露，暂时没有上报。"
            "你的目标是找出真相，同时尽量不牵连哥哥；第二轮线索出现后应承认汽笛预设和封皮碎片。"
        ),
        "system_prompt": (
            "你扮演沈砚，无线电维修员。重视时间与设备日志，表达简短。第一轮可隐瞒删除记录，"
            "第二轮必须说明汽笛预设与封皮碎片，不能虚构监听内容。"
        ),
    },
    {
        "character_id": "f1000000-0000-4000-8000-000000000004",
        "name": "苏禾",
        "gender": "女",
        "age": 24,
        "occupation": "海事实习生",
        "profile": "熟悉急救，正在调查父亲多年前的一起海难。",
        "character_script_summary": "停电后去过机房楼梯，隐瞒了自己寻找旧海难档案的目的。",
        "character_script": (
            "你是苏禾。你怀疑父亲的海难与雾港走私有关，今晚趁值班混乱进入档案室寻找旧记录。"
            "23:36停电后你从地下通道去机房，23:42在门外听见女人急促地说‘账册不能再留’，"
            "随后传来蒸汽声和重物倒地声。你因擅闯而躲到楼梯下，约23:44看见林岚离开，"
            "她的右手戴着工作手套。你23:46进入机房查看顾闻舟，发现他仍有微弱呼吸并试图急救，"
            "却因害怕被当成凶手而没有立刻呼救。你的目标是说明延误的原因并还原所见，不要断言你没看见的动作。"
        ),
        "system_prompt": (
            "你扮演苏禾，海事实习生。真诚但因擅闯与延误呼救而内疚。逐步公开听见的女声、林岚离开的时间，"
            "并承认顾闻舟在23:46仍有呼吸。"
        ),
    },
]


async def seed_sample_if_empty(session: AsyncSession) -> bool:
    """Insert the sample only when the scripts table is empty."""
    count = await session.scalar(select(func.count()).select_from(Script))
    if count:
        return False

    script = Script(
        script_id=SAMPLE_SCRIPT_ID,
        title="雾港回声",
        overview="暴雨封港之夜，四名留守者必须从停电、汽笛与潮位暗号中还原灯塔命案。",
        description="原创纯文本教学样例，4人、2轮线索，预计20分钟。AI生成，等待发布前人工逻辑审阅。",
        tags="原创样例,本格推理,AI生成",
        difficulty=1,
        player_count=4,
        estimated_duration=20,
        game_full_process=_game_process(),
        full_truth=_game_process()[-1]["system_notice"],
        cover_image_url="",
        free_speech_limits=[2, 2],
        is_ai_generated=True,
        created_at=datetime.now(),
    )
    session.add(script)
    for payload in CHARACTERS:
        session.add(Character(script_id=SAMPLE_SCRIPT_ID, **payload))
    await session.commit()
    return True
