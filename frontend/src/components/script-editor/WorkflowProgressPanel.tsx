import { Check, Circle, Loader2, RefreshCw, X } from "lucide-react";

import type { AssetPhase, AssetProgress } from "@/types/editor";

export function ConvertProgressPanel({
  convertProgress,
  onRetry,
}: {
  convertProgress: AssetProgress | null;
  onRetry?: (taskId: string) => Promise<void>;
}) {
  const phases = convertProgress?.phases || [];

  return (
    <div className="h-full flex flex-col p-5 overflow-y-auto scrollbar-thin">
      <h3 className="text-base font-bold mb-1">结构化数据转化</h3>
      <p className="text-xs text-muted-foreground mb-5">
        正在通过多步 LLM
        调用将终稿转化为结构化游戏数据，全部完成后将展示数据供您审阅和修改
      </p>

      {phases.length > 0 ? (
        <div className="space-y-4">
          {phases.map((phase) => (
            <PhaseCard key={phase.id} phase={phase} onRetry={onRetry} />
          ))}
        </div>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center gap-3">
          <div className="w-10 h-10 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          <p className="text-sm text-muted-foreground">初始化中...</p>
        </div>
      )}
    </div>
  );
}

export function AssetGenerationProgress({
  assetProgress,
  onRetry,
}: {
  assetProgress: AssetProgress | null;
  onRetry: (taskId: string) => Promise<void>;
}) {
  const phases = assetProgress?.phases || [];

  return (
    <div className="h-full flex flex-col p-5 overflow-y-auto scrollbar-thin">
      <h3 className="text-base font-bold mb-1">资源生成</h3>
      <p className="text-xs text-muted-foreground mb-5">
        正在为剧本生成图片、语音和向量数据
      </p>

      {phases.length > 0 ? (
        <div className="space-y-4">
          {phases.map((phase) => (
            <PhaseCard key={phase.id} phase={phase} onRetry={onRetry} />
          ))}
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center">
          <div className="w-10 h-10 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      )}
    </div>
  );
}

function PhaseCard({
  phase,
  onRetry,
  retryable = true,
}: {
  phase: AssetPhase;
  onRetry?: (taskId: string) => Promise<void>;
  retryable?: boolean;
}) {
  const completedCount = phase.tasks.filter(
    (task) => task.status === "complete" || task.status === "skipped"
  ).length;
  const total = phase.tasks.length;
  const allDone = completedCount === total;
  const hasRunning = phase.tasks.some((task) => task.status === "running");
  const techColors: Record<string, string> = {
    Embedding: "bg-blue-500/20 text-blue-400",
    "Text-to-Image": "bg-purple-500/20 text-purple-400",
    "Text-to-Speech": "bg-amber-500/20 text-amber-400",
  };

  return (
    <div
      className={`rounded-lg border p-3 ${
        allDone
          ? "border-green-500/30 bg-green-500/5"
          : hasRunning
          ? "border-primary/30 bg-primary/5"
          : "border-border/30"
      }`}
    >
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-2">
          {allDone ? (
            <Check className="w-4 h-4 text-green-500" />
          ) : hasRunning ? (
            <Loader2 className="w-4 h-4 text-primary animate-spin" />
          ) : (
            <Circle className="w-4 h-4 text-muted-foreground/50" />
          )}
          <span className="text-sm font-medium">{phase.label}</span>
        </div>
        <div className="flex flex-col items-end gap-0.5">
          <div className="flex items-center gap-2">
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded ${
                techColors[phase.tech] || "bg-secondary text-muted-foreground"
              }`}
            >
              {phase.tech}
            </span>
            <span className="text-xs text-muted-foreground">
              {completedCount}/{total}
            </span>
          </div>
          {phase.model && (
            <span className="text-[9px] text-muted-foreground/40">
              powered by {phase.model}
            </span>
          )}
        </div>
      </div>
      <div className="space-y-1.5">
        {phase.tasks.map((task) => (
          <TaskRow
            key={task.id}
            task={task}
            onRetry={retryable ? onRetry : undefined}
          />
        ))}
      </div>
    </div>
  );
}

function TaskRow({
  task,
  onRetry,
}: {
  task: { id: string; label: string; status: string; reason?: string };
  onRetry?: (taskId: string) => Promise<void>;
}) {
  return (
    <div
      className={`flex items-center justify-between py-1.5 px-2.5 rounded ${
        task.status === "failed" ? "bg-red-500/10" : ""
      }`}
    >
      <div className="flex items-center gap-2">
        {task.status === "complete" && (
          <Check className="w-3.5 h-3.5 text-green-500 shrink-0" />
        )}
        {task.status === "running" && (
          <div className="w-3.5 h-3.5 rounded-full bg-primary/60 animate-pulse shrink-0" />
        )}
        {task.status === "pending" && (
          <Circle className="w-3.5 h-3.5 text-muted-foreground/30 shrink-0" />
        )}
        {task.status === "failed" && (
          <X className="w-3.5 h-3.5 text-red-400 shrink-0" />
        )}
        {task.status === "skipped" && (
          <Circle className="w-3.5 h-3.5 text-muted-foreground/50 shrink-0" />
        )}
        <span
          className={`text-xs ${
            task.status === "complete"
              ? "text-muted-foreground"
              : task.status === "failed"
              ? "text-red-400"
              : ""
          }`}
        >
          {task.label}
          {task.status === "skipped" && task.reason
            ? `（已跳过：${task.reason}）`
            : ""}
        </span>
      </div>
      {task.status === "failed" && onRetry && (
        <button
          onClick={() => onRetry(task.id)}
          className="flex items-center gap-1 text-xs text-primary hover:text-primary/80 transition-colors"
        >
          <RefreshCw className="w-3 h-3" />
          重试
        </button>
      )}
    </div>
  );
}
