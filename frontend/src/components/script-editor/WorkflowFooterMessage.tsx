import { useEffect, useState } from "react";

export const WORKFLOW_WAIT_MESSAGE =
  "单个节点可能耗时数分钟，且剧本越复杂耗时越久，请耐心等待～";

export function WorkflowFooterMessage({ isWorking }: { isWorking: boolean }) {
  const [elapsed, setElapsed] = useState(false);
  useEffect(() => {
    if (!isWorking) return;
    const timer = setTimeout(() => setElapsed(true), 10000);
    return () => clearTimeout(timer);
  }, [isWorking]);
  if (!isWorking || !elapsed) return null;
  return <p role="status" className="border-l-2 border-primary/25 px-3 py-1 text-xs leading-relaxed text-muted-foreground">{WORKFLOW_WAIT_MESSAGE}</p>;
}
