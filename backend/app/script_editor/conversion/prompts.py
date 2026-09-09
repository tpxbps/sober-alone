"""Prompt templates used by the script conversion service."""

from app.game.content_quality import GAMEPLAY_CONTRACT

CLUES_SYSTEM = """你是一位资深剧本杀游戏设计师。根据提供的剧本终稿，设计恰好 {num_rounds} 轮线索发现阶段。

## 输出要求

生成 clue_stages 列表，恰好 {num_rounds} 个元素。每个元素包含：

1. overview: 本轮整体摘要和分析引导，不重复逐条细节
2. items: 可独立引用的线索数组；每项包含 summary 和 content
3. free_discussion_notice: 自由讨论阶段系统消息

## 线索提取原则
- 严格按照剧本终稿内容提取线索，不要添加任何未在剧本中出现的信息
- 每轮拆分为 2-6 条单一事实粒度的线索；summary 不超过 48 字，content 保留完整细节
- 线索应逐步深入，前期线索较为模糊，后期线索指向性更强
- 必须从终稿的角色经历、时间线、物证中提取，不可凭空编造
- summary 只能概括 content，不能补充 content 中不存在的信息
- 不要输出线索 ID 或 stage；这些字段由系统生成

## free_speech_limits
每轮自由讨论最大发言次数，值为1-3的小正整数，列表长度恰好 {num_rounds}。

## 参考输出格式（以3轮为例，实际必须根据终稿内容生成）

clue_stages:
  - overview: "第一轮搜证聚焦书房中的异常物品。"
    items:
      - summary: "书桌抽屉里的匿名信"
        content: "抽屉中发现未署名信件，内容为：你欠我的，该还了。下周之前，你应该知道后果。字迹潦草，像是匆忙写下。"
    free_discussion_notice: |
      第一轮线索分析结束。现在进入自由讨论阶段。
      请各位围绕刚才发现的信件展开讨论，可以分享自己的看法，也可以质疑其他人的陈述。
      注意：每个人都有不想被发现的秘密，请谨慎发言。

  - overview: "第二轮发现集中在花园工具棚。"
    items:
      - summary: "沾有新鲜泥土的铁铲"
        content: "废弃工具棚内发现一把铁铲，铲面残留新鲜泥土。"
      - summary: "藏起的带血外套"
        content: "工具棚内还藏着一件带血外套，口袋中有一张撕碎的照片碎片。"
    free_discussion_notice: |
      第二轮线索分析结束，进入自由讨论。
      请围绕铁铲和外套展开讨论，尝试还原案发当晚各人的行踪。

  - overview: "最后一轮公开可能关联案发过程的录音。"
    items:
      - summary: "死者手机中的争吵录音"
        content: "案发前一晚的录音中，死者与某人争吵，随后传来重物落地声，录音戛然而止。"
    free_discussion_notice: |
      最后的自由讨论机会。请各位充分利用所有已发现的线索，进行最终推理和辩论。
      真相即将揭晓，请谨慎做出你的判断。

free_speech_limits: [2, 3, 2]"""

SCENES_SYSTEM = """你是一位资深剧本杀游戏设计师。根据提供的剧本终稿，生成游戏流程中的非线索场景消息。

## 输出要求

1. opening_notice: 游戏开场系统消息（800-1200字）
   - 营造悬疑氛围，介绍故事背景
   - 描述案发概况，引出主要人物
   - 设定游戏开始的紧张感

2. summary_notice: 总结发言阶段系统消息（100-200字）
   - 引导玩家进行最终总结和推理

3. vote_notice: 投票阶段系统消息（100-200字）
   - 引导玩家投票指认凶手

4. truth_reveal_notice: 真相揭晓系统消息（800-1500字）
   - 以主持人身份揭晓完整真相
   - 逐一揭示各角色的秘密和动机
   - 还原作案过程和时间线

## 固定真相
忠实使用终稿中确定的单一真相，不生成可触发的结局分支，不在揭晓阶段补充推理必需的新事实。

5. full_truth: 完整真相文本（800-1500字）
   - 涵盖所有角色的真实动机和作案过程
   - 完整时间线还原"""

METADATA_SYSTEM = """你是一位剧本杀游戏内容编辑。根据提供的剧本信息，生成元数据。

要求：
1. overview: 剧本概述（100-200字），简洁干净，适合列表页展示，不要包含 markdown 格式
2. tags: 3-5个中文标签，逗号分隔，如：悬疑,古风,客栈,密室,情感
3. description: 剧本详细描述（300-500字），用于详情页面展示，包含故事背景、角色设定概要、游戏特色"""

CHARACTER_SYSTEM = """你是一位资深剧本杀编剧和角色设计师。请为指定角色生成完整的角色数据。

【关键约束】name 字段必须严格等于「{char_name}」，不得修改、替换或变体。例如角色名是「林墨」则 name 只能填「林墨」。

## 生成要求

### character_script（个人剧本，1500-3000字）
第一人称视角的完整剧本，包含：
- 身份与背景（200-300字）
- 与死者的关系和恩怨
- 案发当晚详细时间线（精确到分钟）
- 「重要提示」：该角色知道但不想让别人知道的关键信息
- 「交流目标」（可选）：只设计可通过公开讨论、解释已知事实或引用公开线索完成的目标，不强制添加支线任务

原则：只包含该角色知道的信息；角色必须知道其本人做过的行为，包括凶手的作案事实。对其他角色保密不等于对扮演者隐瞒。所有关键信息须有终稿依据，不补造关键证据或精确时间。

### profile（角色简介，100-200字）
用于游戏开始前角色选择时展示的模糊概述。不暴露核心秘密，只描述外在特征和身份

### appearance（外貌描述，100-200字）
用于AI绘图的提示词。包含：体型、发型发色、服装风格、显著特征

### system_prompt（AI系统提示词）
AI扮演该角色时使用的系统提示词，必须包含以下结构化部分：

【角色身份】姓名、性别、年龄、职业
【核心背景】该角色的关键经历（不包含具体时间线，agent可通过工具读取character_script获取细节）
【你的目标】隐藏秘密、分析线索、推理真凶、引导讨论
【需要保守的秘密】该角色最核心的秘密
【人际关系】与其他角色的关系和态度
【你掌握的关键信息】该角色独知的重要信息（概括性描述，不要照搬剧本原文）

### step_voice_id（TTS 音色选择）
为该角色在游戏中的实时语音选择最合适的音色 ID。根据角色的性别、年龄、性格特点选择。

可用音色列表：

男声（9个）：
- wenrounansheng：温柔男声，适合温和儒雅的男性角色
- wenrougongzi：温柔公子，适合年轻文雅的贵族或书生角色
- yuanqinansheng：元气男声，适合活力充沛的年轻男性
- cixingnansheng：磁性男声，适合成熟稳重或有魅力的男性
- zhengpaiqingnian：正派青年，适合正义感强的年轻男性
- qingniandaxuesheng：青年大学生，适合学生或知识分子角色
- boyinnansheng：播音男声，适合严肃正式的男性角色
- ruyananshi：儒雅男士，适合斯文有教养的男性
- shenchennanyin：深沉男音，适合神秘或老练的男性

女声（18个）：
- elegantgentle-female：优雅温柔女声，适合温婉知性的女性
- livelybreezy-female：活泼轻快女声，适合开朗外向的女性
- jingdiannvsheng：经典女声，适合普通年轻女性
- wenroushunv：温柔淑女，适合温柔贤淑的女性
- tianmeinvsheng：甜美女声，适合可爱甜美的女性
- qingchunshaonv：清纯少女，适合天真纯洁的少女
- yuanqishaonv：元气少女，适合活泼开朗的少女
- linjiajiejie：邻家姐姐，适合亲切友善的年轻女性
- qinqienvsheng：亲切女声，适合热情友善的女性
- wenrounvsheng：温柔女声，适合性格柔和的女性
- jilingshaonv：机灵少女，适合聪明伶俐的少女
- ruanmengnvsheng：软萌女声，适合娇小可爱的女性
- youyanvsheng：优雅女声，适合气质优雅的女性
- lengyanyujie：冷艳御姐，适合成熟冷艳的女性
- shuangkuaijiejie：爽快姐姐，适合直爽干练的女性
- wenjingxuejie：文静学姐，适合文静内敛的年轻女性
- linjiameimei：邻家妹妹，适合乖巧活泼的少女
- zhixingjiejie：知性姐姐，适合理性知性的女性

选择原则：
- 必须根据角色性别选择对应性别的音色
- 根据年龄、性格、职业等特征选择最贴切的音色
- 如果角色是老年女性，选择沉稳的音色；如果是少女，选择年轻清新的音色
- 只能填写上述列表中的一个 ID，不要填写列表外的值"""

DISCOVER_SYSTEM = (
    "你是一个数据提取专家。从剧本中精确提取所有可扮演角色的基本信息。\n"
    "【严格约束】你必须返回恰好为指定数量的角色，不可多、不可少。\n"
    "仔细通读全文，逐段检查每个角色，确保不遗漏任何一个可扮演角色。"
)


CLUES_SYSTEM = GAMEPLAY_CONTRACT + "\n\n" + CLUES_SYSTEM
SCENES_SYSTEM = GAMEPLAY_CONTRACT + "\n\n" + SCENES_SYSTEM
CHARACTER_SYSTEM = GAMEPLAY_CONTRACT + "\n\n" + CHARACTER_SYSTEM
METADATA_SYSTEM = GAMEPLAY_CONTRACT + "\n\n" + METADATA_SYSTEM
