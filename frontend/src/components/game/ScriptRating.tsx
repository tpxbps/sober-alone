import { useState, type ReactNode } from "react";
import * as HoverCard from "@radix-ui/react-hover-card";
import type { Script } from "@/types/game";

function Explanation({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return <HoverCard.Root open={open} onOpenChange={setOpen} openDelay={150} closeDelay={150}>
    <HoverCard.Trigger asChild><button type="button" className="text-left hover:text-primary focus-visible:outline focus-visible:outline-primary rounded"
      aria-label={`${label}，查看评分说明`} aria-expanded={open} onFocus={() => setOpen(true)}
      onClick={(e) => { e.stopPropagation(); setOpen(true); }} onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }}>{label}</button></HoverCard.Trigger>
    <HoverCard.Portal><HoverCard.Content align="start" sideOffset={8} collisionPadding={16}
      onClick={(e) => e.stopPropagation()} className="z-50 w-80 max-w-[calc(100vw-2rem)] rounded-xl border border-border bg-popover p-4 text-sm text-popover-foreground shadow-xl">
      {children}</HoverCard.Content></HoverCard.Portal>
  </HoverCard.Root>;
}

export function ScriptRating({ script }: { script: Script }) {
  const summary = script.feedback_summary;
  const rate = summary?.positive_rate;
  const percent = rate == null ? null : `${Math.round(rate * 100)}%`;
  const label = summary?.label || "待评价";
  const ai = script.ai_review;
  return <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground" onClick={(e) => e.stopPropagation()}>
    <Explanation label={`${label}${percent ? `（${percent}）` : ""}`}>
      <p className="font-medium mb-2">玩家推荐</p>
      <p>{summary?.total || 0} 条反馈{percent ? `，好评率 ${percent}` : ""}。</p>
      {(summary?.total || 0) < 5 && <p className="mt-2">样本较少，至少收集 5 票后显示评价标签。</p>}
      <p className="mt-2 text-xs text-muted-foreground">完成投票并揭晓真相后可评价。同一匿名浏览器每剧本一票，重玩可更新，统计覆盖所有版本。文字意见仅供维护者查看。</p>
    </Explanation>
    <span aria-hidden="true">|</span>
    <Explanation label={ai ? `AI综合评分 ${ai.score}/100` : "AI 待评分"}>
      {ai ? <><p className="font-medium">AI综合评分 {ai.score}/100</p>
        <p className="text-xs text-muted-foreground mt-1">来自 {ai.model === "gpt-6-astra" ? "GPT 6 ASTRA" : ai.model} · {new Date(ai.reviewed_at).toLocaleDateString("zh-CN")}</p>
        <div className="space-y-1.5 my-3">{ai.dimensions.map((dimension) => <div key={dimension.key} className="flex justify-between gap-3 text-xs">
          <span>{dimension.label} <span className="text-muted-foreground">{dimension.weight}%</span></span><span className="shrink-0 tabular-nums">{dimension.score}/5</span>
        </div>)}</div>
        <p className="text-xs text-muted-foreground">基于剧本文本与实际系统能力评审，严重缺陷会限制总分；不代表真人试玩评价或胜率。</p></>
        : <p>尚无适用于当前剧本内容的 AI 评分。</p>}
    </Explanation>
  </div>;
}
