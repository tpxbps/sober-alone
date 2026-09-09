import { useState } from "react";
import { useEditorStore } from "@/stores/editorStore";
import type { QualityReport } from "@/types/editor";

export function QualityReviewStage({ report, isLoading, error }: {
  report: QualityReport; isLoading: boolean; error: string | null;
}) {
  const resume = useEditorStore((state) => state.resumeWorkflow);
  const [accepted, setAccepted] = useState(false);
  const run = (action: string) => resume(action, undefined, undefined, undefined, undefined, undefined, report.report_id);
  return <div className="h-full flex flex-col">
    <div className="p-4 border-b border-border"><h3 className="font-medium">{report.status === "incomplete" ? "质量检查未完成" : "发现需要处理的质量问题"}</h3>
      <p className="mt-1 text-xs text-muted-foreground">请修改后重新检查；AI 判断可能有误，你也可以阅读问题并明确接受风险。</p></div>
    <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-3">
      {(error || report.error) && <p role="alert" className="text-sm text-amber-400">{error || report.error}</p>}
      {report.findings.map((finding, index) => <article key={index} className="rounded-lg border border-border p-4 space-y-2 text-sm">
        <div className="flex flex-wrap gap-2"><span className="text-amber-400">{{ critical: "严重", major: "重要", minor: "建议" }[finding.severity]}</span><span className="text-xs text-muted-foreground break-all">{finding.field}</span></div>
        <blockquote className="border-l-2 border-primary/40 pl-3 whitespace-pre-wrap text-muted-foreground">{finding.evidence || "该字段为空"}</blockquote>
        <p>{finding.impact}</p><p className="text-primary">修改建议：{finding.suggestion}</p>
      </article>)}
    </div>
    <div className="p-4 border-t border-border space-y-3">
      <div className="flex gap-2"><button disabled={isLoading} onClick={() => run("revise")} className="flex-1 py-2.5 rounded-lg bg-primary text-primary-foreground disabled:opacity-50">返回修改</button>
        <button disabled={isLoading} onClick={() => run("retry_quality")} className="px-4 py-2.5 rounded-lg bg-secondary disabled:opacity-50">重新检查</button></div>
      <label className="flex gap-2 text-xs text-muted-foreground"><input type="checkbox" checked={accepted} disabled={isLoading} onChange={(e) => setAccepted(e.target.checked)} />我已阅读报告，接受这些问题或检查未完成可能影响游戏体验</label>
      <button disabled={isLoading || !accepted} onClick={() => run("accept_risk")} className="text-sm text-amber-400 disabled:opacity-40">接受风险并继续保存</button>
    </div>
  </div>;
}
