import { useEffect, useState } from "react";

export const WORKFLOW_WAIT_MESSAGE =
  "单个节点可能耗时数分钟，且剧本越复杂耗时越久，请耐心等待～";
export const WORKFLOW_MOTTO =
  "「不诱于誉，不恐于诽，率道而行，端然正己。」 剧本创作工作流全程由 deepseek-v4-flash 稳定执行。";

const TYPE_INTERVAL_MS = 42;
const FULL_MESSAGE_HOLD_MS = 2400;

export function WorkflowFooterMessage({ isWorking }: { isWorking: boolean }) {
  const [messageIndex, setMessageIndex] = useState(0);
  const [visibleLength, setVisibleLength] = useState(1);
  const messages = [WORKFLOW_WAIT_MESSAGE, WORKFLOW_MOTTO];
  const activeMessage = messages[messageIndex];

  useEffect(() => {
    if (!isWorking) return;

    const messageIsComplete = visibleLength >= activeMessage.length;
    const timer = window.setTimeout(
      () => {
        if (messageIsComplete) {
          setMessageIndex((current) => (current + 1) % messages.length);
          setVisibleLength(1);
        } else {
          setVisibleLength((current) => current + 1);
        }
      },
      messageIsComplete ? FULL_MESSAGE_HOLD_MS : TYPE_INTERVAL_MS
    );
    return () => window.clearTimeout(timer);
  }, [activeMessage, isWorking, messages.length, visibleLength]);

  if (!isWorking) return <span>{WORKFLOW_MOTTO}</span>;

  return (
    <span role="status" aria-label={activeMessage} className="inline-flex items-center">
      <span>{activeMessage.slice(0, visibleLength)}</span>
      <span aria-hidden="true" className="ml-0.5 h-3.5 w-px animate-pulse bg-primary/70" />
    </span>
  );
}
