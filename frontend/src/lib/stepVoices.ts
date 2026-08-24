export interface StepVoiceOption {
  id: string;
  label: string;
}

export interface StepVoiceGroup {
  label: string;
  voices: StepVoiceOption[];
}

/** step-tts-mini voices accepted by the backend validation layer. */
export const STEP_VOICE_GROUPS: StepVoiceGroup[] = [
  {
    label: "男声（9 个）",
    voices: [
      { id: "wenrounansheng", label: "温柔男声" },
      { id: "wenrougongzi", label: "温柔公子" },
      { id: "yuanqinansheng", label: "元气男声" },
      { id: "cixingnansheng", label: "磁性男声" },
      { id: "zhengpaiqingnian", label: "正派青年" },
      { id: "qingniandaxuesheng", label: "青年大学生" },
      { id: "boyinnansheng", label: "播音男声" },
      { id: "ruyananshi", label: "儒雅男士" },
      { id: "shenchennanyin", label: "深沉男音" },
    ],
  },
  {
    label: "女声（18 个）",
    voices: [
      { id: "elegantgentle-female", label: "优雅温柔女声" },
      { id: "livelybreezy-female", label: "活泼轻快女声" },
      { id: "jingdiannvsheng", label: "经典女声" },
      { id: "wenroushunv", label: "温柔淑女" },
      { id: "tianmeinvsheng", label: "甜美女声" },
      { id: "qingchunshaonv", label: "清纯少女" },
      { id: "yuanqishaonv", label: "元气少女" },
      { id: "linjiajiejie", label: "邻家姐姐" },
      { id: "qinqienvsheng", label: "亲切女声" },
      { id: "wenrounvsheng", label: "温柔女声" },
      { id: "jilingshaonv", label: "机灵少女" },
      { id: "ruanmengnvsheng", label: "软萌女声" },
      { id: "youyanvsheng", label: "优雅女声" },
      { id: "lengyanyujie", label: "冷艳御姐" },
      { id: "shuangkuaijiejie", label: "爽快姐姐" },
      { id: "wenjingxuejie", label: "文静学姐" },
      { id: "linjiameimei", label: "邻家妹妹" },
      { id: "zhixingjiejie", label: "知性姐姐" },
    ],
  },
];

export const STEP_VOICE_OPTIONS = STEP_VOICE_GROUPS.flatMap(
  (group) => group.voices
);
