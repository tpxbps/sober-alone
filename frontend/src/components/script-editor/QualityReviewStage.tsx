import { useEditorStore } from "@/stores/editorStore";
import type { QualityReport } from "@/types/editor";
import { normalizeQualityReport } from './qualityReport';

export function QualityReviewStage({ report: savedReport, isLoading, error }: {
  report?: QualityReport | null; isLoading: boolean; error: string | null;
}) {
  const report = normalizeQualityReport(savedReport);
  const resume = useEditorStore((state) => state.resumeWorkflow);
  const run = (action: string) => resume(action, undefined, undefined, undefined, undefined, undefined, report?.report_id);
  return <div className="h-full flex flex-col">
    <div className="p-4 border-b border-border"><h3 className="font-medium">{!report || report.status === "incomplete" ? "质量检查未完成" : "发现需要处理的质量问题"}</h3>
      <p className="mt-1 text-xs text-muted-foreground">这是此前保存的质检报告，仅供参考。返回游戏数据后可以直接进入下一步。</p></div>
    <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-3">
      {(error || report?.error) && <p role="alert" className="text-sm text-warning">{error || report?.error}</p>}
      {!report && <p className="text-sm text-muted-foreground">尚无质检报告，可返回游戏数据继续创作。</p>}
      {report?.findings.map((finding, index) => <article key={index} className="rounded-lg border border-border p-4 space-y-2 text-sm">
        <div className="flex flex-wrap gap-2"><span className="text-warning">{{ critical: "严重", major: "重要", minor: "建议" }[finding.severity]}</span><span className="text-xs text-muted-foreground break-all">{finding.target?.label || "相关剧本内容"}</span></div>
        <blockquote className="border-l-2 border-primary/40 pl-3 whitespace-pre-wrap text-muted-foreground">{finding.evidence || "该字段为空"}</blockquote>
        <p>{finding.impact}</p><p className="text-primary">修改建议：{finding.suggestion}</p>
      </article>)}
    </div>
    <div className="p-4 border-t border-border space-y-3">
      <button disabled={isLoading} onClick={() => run("revise")} className="w-full py-2.5 rounded-lg bg-primary text-primary-foreground disabled:opacity-50">返回游戏数据 · 继续创作</button>
    </div>
  </div>;
}
