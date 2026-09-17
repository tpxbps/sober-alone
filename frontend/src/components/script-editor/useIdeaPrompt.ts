import { useEffect, useState } from 'react';

export const IDEA_EXAMPLES = [
  '故事发生在某家互联网大厂，平台的资深采销、区域经理与各路商家们合作密切、配合默契，或者说他们长期“深度绑定”、“互有走动”，以谋取利益！多年来的“患难与共”让他们成为知己知彼的“人生好友”，傲人的“成绩”也让他们被外界评价为“最佳拍档”，直到，一次意外的出现...',
  '海岛上最后一家旅馆即将停业，老板请四位老客人回来吃一顿告别宴。每个人都曾在这里被他帮助，也都替他保守过一个秘密。台风封航的那晚，餐桌上多出了一封二十年前的信，而写信的人，本不该再出现……',
  '一支解散多年的剧团收到匿名邀请，要在即将拆除的老剧院重演成名作。有人带着亏欠回来，有人终于等到证明自己的机会。开演前，所有人都发现自己的台词被改过；落幕时，那场排练了无数次的死亡，成了真的……',
];

export function useIdeaPrompt(paused: boolean) {
  const [motionReduced, setMotionReduced] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [cursor, setCursor] = useState({ example: 0, length: 0 });
  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setMotionReduced(media.matches);
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    if (paused || motionReduced) return;
    const complete = cursor.length >= IDEA_EXAMPLES[cursor.example].length;
    const timer = setTimeout(() => setCursor(complete ? { example: (cursor.example + 1) % IDEA_EXAMPLES.length, length: 0 } : { ...cursor, length: cursor.length + 1 }), complete ? 8000 : 45);
    return () => clearTimeout(timer);
  }, [cursor, paused, motionReduced]);
  return motionReduced ? IDEA_EXAMPLES[0] : IDEA_EXAMPLES[cursor.example].slice(0, cursor.length);
}
