import { useRef } from "react";
import type { EndingConfig, EndingOutcome, GameDataSections } from "@/types/editor";

const ENDING_LABELS: Record<EndingOutcome, string> = {
  correct: "正确指认", incorrect: "错误指认", tie: "平票", no_votes: "无有效票",
};

export function EndingEditor({ data, onChange }: {
  data: GameDataSections;
  onChange: (value: EndingConfig | null) => void;
}) {
  const previous = useRef<EndingConfig | null>(null);
  const config = data.ending_config;
  const fieldClass = "mt-1 w-full rounded-md border border-border/40 bg-card p-2 text-sm focus:border-primary/50 focus:outline-none";
  return <section className="rounded-lg border border-border/40 p-4 space-y-3">
    <h4 className="text-sm font-semibold">结局设置</h4>
    <label className="block text-xs">结局模式
      <select aria-label="结局模式" className={fieldClass} value={config ? "multiple" : "single"} onChange={(event) => {
        if (event.target.value === "single") {
          previous.current = config || null;
          onChange(null);
        } else onChange(previous.current || {
          mode: "multiple", culprit_character_id: "",
          branches: (Object.keys(ENDING_LABELS) as EndingOutcome[]).map((when) => ({ when, title: ENDING_LABELS[when], text: "" })),
        });
      }}>
        <option value="single">单结局</option><option value="multiple">多结局</option>
      </select>
    </label>
    {config && <p className="text-xs text-muted-foreground">为不同投票结果填写故事后续，所有结局共享同一案件真相。</p>}
    {config && <>
      <label className="block text-xs">真凶
        <select aria-label="真凶" className={fieldClass} value={config.culprit_character_id} onChange={(e) => onChange({ ...config, culprit_character_id: e.target.value })}>
          <option value="">请选择角色</option>
          {data.character_data?.map((c) => <option key={c.character_id} value={c.character_id}>{c.name}</option>)}
        </select>
      </label>
      <div className="grid gap-4 xl:grid-cols-2">
        {(Object.keys(ENDING_LABELS) as EndingOutcome[]).map((when) => {
          const branch = config.branches.find((b) => b.when === when) || { when, title: "", text: "" };
          const update = (key: "title" | "text", value: string) => onChange({ ...config, branches: [
            ...config.branches.filter((b) => b.when !== when), { ...branch, [key]: value },
          ] });
          return <fieldset key={when} className="min-w-0 rounded-md border border-border/30 p-3">
            <legend className="px-1 text-xs font-medium">{ENDING_LABELS[when]}</legend>
            <label className="text-xs">结局标题<input aria-label={`${ENDING_LABELS[when]}结局标题`} maxLength={100} className={fieldClass} value={branch.title} onChange={(e) => update("title", e.target.value)} /></label>
            <label className="mt-2 block text-xs">结局正文<textarea aria-label={`${ENDING_LABELS[when]}结局正文`} maxLength={12000} className={`${fieldClass} min-h-40 resize-y`} value={branch.text} onChange={(e) => update("text", e.target.value)} /></label>
          </fieldset>;
        })}
      </div>
    </>}
  </section>;
}
