import { useRef, useState } from "react";
import { isAxiosError } from "axios";
import { ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { editorApi } from "@/lib/editorApi";
import type { Script } from "@/types/game";

interface ScriptOptimizationDialogProps {
  script: Script;
  onClose: () => void;
  onSaved: (authorized: boolean) => void;
  onRestoreFocus: () => void;
}

export function ScriptOptimizationDialog({ script, onClose, onSaved, onRestoreFocus }: ScriptOptimizationDialogProps) {
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const saving = useRef(false);
  const authorized = script.optimization_authorized ?? true;

  const updateAuthorization = async () => {
    if (saving.current) return;
    saving.current = true;
    setIsSaving(true);
    setError(null);
    setSaved(false);
    try {
      const result = await editorApi.updateOptimizationAuthorization(script.script_id, !authorized);
      if (!result.success) throw new Error("保存失败");
      onSaved(result.optimization_authorized);
      setSaved(true);
    } catch (error) {
      const detail = isAxiosError(error) ? error.response?.data?.detail : null;
      setError(typeof detail === "string" ? detail : "保存授权状态失败，请重试。");
    } finally {
      saving.current = false;
      setIsSaving(false);
    }
  };

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !saving.current) onClose(); }}>
      <DialogContent
        className="flex flex-col overflow-hidden"
        showCloseButton={!isSaving}
        onCloseAutoFocus={(event) => { event.preventDefault(); onRestoreFocus(); }}
      >
        <DialogHeader className="shrink-0 text-left">
          <ShieldCheck className="mb-1 h-6 w-6 text-primary" aria-hidden="true" />
          <DialogTitle className="pr-4 leading-relaxed">授权系统维护者对剧本进行优化</DialogTitle>
          <DialogDescription>为「{script.title}」设置优化授权。</DialogDescription>
        </DialogHeader>

        <p role="status" className="shrink-0 rounded-lg border border-border bg-secondary/30 px-3 py-2 text-sm">
          当前状态：<strong className={authorized ? "text-primary" : "text-foreground"}>{authorized ? "已授权" : "未授权"}</strong>
          {saved && <span className="ml-2 text-muted-foreground">已保存</span>}
        </p>

        <div className="min-h-0 space-y-4 overflow-y-auto pr-1 text-sm leading-6 text-muted-foreground scrollbar-thin">
          <section className="space-y-1">
            <h3 className="font-medium text-foreground">检查与内容微调</h3>
            <p>系统维护者可能按照剧本评分的各个维度进行检查，包括系统匹配与任务可执行性、时间线与因果一致性、证据完整性与可推理性、角色公平性、交流节奏、叙事与人物塑造，以及新手指引与表达清晰度。</p>
            <p>若发现重大缺陷，可能基于当前剧本，针对具体问题进行必要的内容微调或修改，保留故事设定、核心情节、人物关系和案件真相等核心内容。</p>
          </section>
          <section className="space-y-1">
            <h3 className="font-medium text-foreground">丰富图片等资源</h3>
            <p>可能进一步补充或优化剧本资源，包括但不限于优化剧本概览图、角色立绘，或新增线索配图、推进动画等，以改善呈现与游玩体验。</p>
          </section>
          <section className="space-y-1">
            <h3 className="font-medium text-foreground">由你决定是否授权</h3>
            <p>系统默认已授权。你可以随时取消授权，表示不同意系统维护者对你创作的剧本进行任何修改；取消后，维护者将不再进行内容修改或资源优化。你也可以在此重新确认授权。</p>
          </section>
        </div>

        {error && <p role="alert" className="shrink-0 text-sm text-destructive">{error}</p>}
        <DialogFooter className="shrink-0">
          <Button variant="outline" disabled={isSaving} onClick={onClose}>关闭</Button>
          <Button variant={authorized ? "secondary" : "default"} disabled={isSaving} onClick={() => void updateAuthorization()}>
            {isSaving ? "保存中…" : authorized ? "取消授权" : "确认授权"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
