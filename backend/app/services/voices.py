"""Portable system voices; legacy Step identifiers remain readable."""

MINIMAX_VOICES = (
    ("male-qn-qingse", "青涩青年", "男"),
    ("male-qn-jingying", "精英青年", "男"),
    ("male-qn-badao", "霸道青年", "男"),
    ("male-qn-daxuesheng", "青年大学生", "男"),
    ("Chinese (Mandarin)_Gentleman", "温润男声", "男"),
    ("Chinese (Mandarin)_Reliable_Executive", "沉稳高管", "男"),
    ("Chinese (Mandarin)_Humorous_Elder", "老年男声", "男"),
    ("Chinese (Mandarin)_Radio_Host", "电台男声", "男"),
    ("female-shaonv", "少女", "女"),
    ("female-yujie", "御姐", "女"),
    ("female-chengshu", "成熟女性", "女"),
    ("female-tianmei", "甜美女性", "女"),
    ("Chinese (Mandarin)_Warm_Bestie", "温暖闺蜜", "女"),
    ("Chinese (Mandarin)_Gentle_Senior", "温柔学姐", "女"),
    ("Chinese (Mandarin)_Kind-hearted_Elder", "花甲奶奶", "女"),
    ("Chinese (Mandarin)_Wise_Women", "阅历姐姐", "女"),
)
VOICE_IDS = frozenset(item[0] for item in MINIMAX_VOICES)
LEGACY_VOICES = {
    "cixingnansheng": "Chinese (Mandarin)_Radio_Host",
    "wenrounansheng": "Chinese (Mandarin)_Gentleman",
    "wenrougongzi": "Chinese (Mandarin)_Gentleman",
    "yuanqinansheng": "male-qn-qingse",
    "zhengpaiqingnian": "male-qn-jingying",
    "qingniandaxuesheng": "male-qn-daxuesheng",
    "boyinnansheng": "Chinese (Mandarin)_Radio_Host",
    "ruyananshi": "Chinese (Mandarin)_Gentleman",
    "shenchennanyin": "Chinese (Mandarin)_Reliable_Executive",
    "qingchunshaonv": "female-shaonv",
    "yuanqishaonv": "female-tianmei",
    "lengyanyujie": "female-yujie",
    "shuangkuaijiejie": "Chinese (Mandarin)_Warm_Bestie",
    "wenjingxuejie": "Chinese (Mandarin)_Gentle_Senior",
    "zhixingjiejie": "Chinese (Mandarin)_Wise_Women",
    "youyanvsheng": "female-chengshu",
    "wenroushunv": "Chinese (Mandarin)_Gentle_Senior",
    "wenrounvsheng": "Chinese (Mandarin)_Gentle_Senior",
    "elegantgentle-female": "Chinese (Mandarin)_Gentle_Senior",
    "livelybreezy-female": "Chinese (Mandarin)_Warm_Bestie",
    "jingdiannvsheng": "female-chengshu",
    "tianmeinvsheng": "female-tianmei",
    "linjiajiejie": "Chinese (Mandarin)_Warm_Bestie",
    "qinqienvsheng": "Chinese (Mandarin)_Gentle_Senior",
    "jilingshaonv": "female-shaonv",
    "ruanmengnvsheng": "female-tianmei",
    "linjiameimei": "female-shaonv",
}


def resolve_minimax_voice(voice_id: str = "", character: dict | None = None) -> str:
    if voice_id in VOICE_IDS:
        return voice_id
    info = character or {}
    female = str(info.get("gender", "")).lower() in {"女", "女性", "female", "f"}
    description = " ".join(str(info.get(k, "")) for k in ("occupation", "profile"))
    try:
        age = int(info.get("age", 0))
    except (ValueError, TypeError):
        age = 0
    if age >= 60:
        return (
            "Chinese (Mandarin)_Kind-hearted_Elder"
            if female
            else "Chinese (Mandarin)_Humorous_Elder"
        )
    if age and age <= 22:
        return "female-shaonv" if female else "male-qn-daxuesheng"
    if any(word in description for word in ("老板", "总裁", "掌门", "威严", "强势")):
        return "female-yujie" if female else "Chinese (Mandarin)_Reliable_Executive"
    if any(word in description for word in ("温柔", "文雅", "儒雅", "书生")):
        return "Chinese (Mandarin)_Gentle_Senior" if female else "Chinese (Mandarin)_Gentleman"
    return LEGACY_VOICES.get(voice_id, "female-chengshu" if female else "male-qn-jingying")
