import { useState, type ReactNode } from "react";
import * as Tooltip from "@radix-ui/react-tooltip";
import type { Script } from "@/types/game";

function Explanation({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return <Tooltip.Root open={open} onOpenChange={setOpen}>
    <Tooltip.Trigger asChild><button type="button" className="text-left hover:text-primary focus-visible:outline focus-visible:outline-primary rounded"
      aria-label={`${label}，打开剧本详情`}>{label}</button></Tooltip.Trigger>
    <Tooltip.Portal><Tooltip.Content align="start" sideOffset={8} collisionPadding={16}
      data-rating-explanation="" onClick={() => setOpen(false)}
      onPointerDown={(event) => event.preventDefault()}
      className="z-50 w-max max-w-[calc(100vw-2rem)] cursor-pointer rounded-xl border border-border bg-popover p-3 text-sm text-popover-foreground shadow-xl">
      {children}
    </Tooltip.Content></Tooltip.Portal>
  </Tooltip.Root>;
}

export function ScriptRating({ script }: { script: Script }) {
  const summary = script.feedback_summary;
  const rate = summary?.positive_rate;
  const percent = rate == null ? null : `${Math.round(rate * 100)}%`;
  const label = summary?.label || "待评价";
  const ai = script.ai_review;
  return <Tooltip.Provider delayDuration={150}>
    <div className="ml-auto inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap text-xs text-muted-foreground">
      <Explanation label={`${label}${percent ? `（${percent}）` : ""}`}>
        <p className="font-medium">玩家推荐</p>
        <p className="mt-1 text-xs text-muted-foreground">完成投票并揭晓真相后可评价</p>
      </Explanation>
      <span aria-hidden="true">|</span>
      <Explanation label={ai ? `AI评分: ${ai.score}` : "AI 待评分"}>
        {ai ? <div className="w-72 max-w-full whitespace-normal">
          <p className="font-medium">AI评分: {ai.score} <span className="text-xs font-normal text-muted-foreground">（{ai.model === "gpt-6-astra" ? "GPT 6 ASTRA" : ai.model}）</span></p>
          <div className="space-y-1.5 mt-3">{ai.dimensions.map((dimension) => <div key={dimension.key} className="flex justify-between gap-3 text-xs">
            <span>{dimension.label} <span className="text-muted-foreground">{dimension.weight}%</span></span><span className="shrink-0 tabular-nums">{dimension.score}/5</span>
          </div>)}</div>
        </div> : <p>尚无 AI 评分</p>}
      </Explanation>
    </div>
  </Tooltip.Provider>;
}
