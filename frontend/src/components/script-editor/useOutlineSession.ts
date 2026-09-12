import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { editorApi } from "@/lib/editorApi";
import { applyOutlineDelta, applyOutlineSnapshot } from "@/lib/outlineStream";
import { useEditorStore } from "@/stores/editorStore";
import { getPhaseFromStep } from "@/types/editor";
import type { OutlineCommand, OutlineDelta, OutlineProgress } from "@/types/outline";

export function useOutlineSession(threadId: string | null) {
  const [progress, setProgress] = useState<OutlineProgress | null>(null);
  const latest = useRef<OutlineProgress | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const requestInFlight = useRef(false);
  const mounted = useRef(true);
  const update = useCallback((incoming: OutlineProgress) => {
    if (applyOutlineSnapshot(latest.current, incoming) !== incoming) return false;
    latest.current = incoming;
    setProgress(incoming);
    return true;
  }, []);
  const refresh = useCallback(async () => {
    if (!threadId) return;
    const response = await editorApi.getState(threadId);
    const editor = useEditorStore.getState();
    if (!mounted.current || editor.threadId !== threadId ||
        (!editor.isStarting && getPhaseFromStep(editor.currentStep) !== "outline")) return;
    if (response.outline_progress && !update(response.outline_progress)) return;
    const session = response.state.outline_session;
    if (session) {
      useEditorStore.setState({
        workflowState: response.state, interruptInfo: response.interrupt, isStarting: false,
        currentStep: response.current_step === "init" ? "generate_outline" : response.current_step, scriptTitle: response.state.script_title,
        error: response.outline_progress?.error || null,
      });
    }
  }, [threadId, update]);

  useEffect(() => {
    if (!threadId) return;
    mounted.current = true;
    let disposed = false;
    let reconnect: ReturnType<typeof setTimeout> | undefined;
    let close: (() => void) | undefined;
    const safeRefresh = () => { if (!disposed) void refresh().catch(() => {}); };
    const connect = () => {
      if (disposed) return;
      close = editorApi.openProgressStream(threadId, () => {}, () => {}, () => {
        if (!disposed) reconnect = setTimeout(connect, 1500);
      }, (type, data) => {
        if (disposed) return;
        if (type === "outline_delta") {
          const applied = applyOutlineDelta(latest.current, data as OutlineDelta);
          if (applied.refresh) safeRefresh();
          else if (applied.value) update(applied.value);
        } else {
          update(data as OutlineProgress);
          if ((data as OutlineProgress).session?.pending_question ||
              ["ready", "needs_revision"].includes((data as OutlineProgress).session?.status)) safeRefresh();
        }
      });
    };
    safeRefresh();
    connect();
    const poll = setInterval(safeRefresh, 2500);
    return () => { disposed = true; mounted.current = false; close?.(); clearTimeout(reconnect); clearInterval(poll); };
  }, [threadId, refresh, update]);

  const act = useCallback(async (command: Omit<OutlineCommand, "request_id" | "expected_revision">) => {
    if (!threadId || requestInFlight.current) return false;
    requestInFlight.current = true;
    setBusy(true);
    setError("");
    useEditorStore.setState({ error: null });
    const request: OutlineCommand = {
      ...command, request_id: crypto.randomUUID(),
      expected_revision: latest.current?.control.revision || latest.current?.revision || 1,
    };
    try {
      // The same request ID is used if a response is lost.
      try { await editorApi.outlineAction(threadId, request); }
      catch (err) {
        if (axios.isAxiosError(err) && !err.response) await editorApi.outlineAction(threadId, request);
        else throw err;
      }
      if (command.action === "save") {
        const deadline = Date.now() + 30000;
        while (true) {
          const result = await editorApi.getOperation(threadId, request.request_id);
          if (result.operation_status === "failed") throw new Error(result.error_message || "大纲保存失败，请重试");
          if (result.operation_status === "complete" && result.state) {
            if (result.outline_progress) update(result.outline_progress);
            useEditorStore.setState({ workflowState: result.state, interruptInfo: result.interrupt, error: null });
            break;
          }
          if (Date.now() >= deadline) throw new Error("尚未确认保存结果，请稍后重试；编辑内容已保留");
          await new Promise(resolve => setTimeout(resolve, 250));
        }
      }
      // Acceptance is durable; a failed/slow snapshot must not turn it into a
      // failed command or keep all controls locked. SSE and polling resync it.
      void refresh().catch(() => {});
      return true;
    } catch (err) {
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null;
      setError(typeof detail === "string" ? detail : err instanceof Error ? err.message : "操作未完成，请重试");
      void refresh().catch(() => {});
      return false;
    } finally {
      requestInFlight.current = false;
      setBusy(false);
    }
  }, [threadId, refresh, update]);
  return { progress, error, busy, act, refresh };
}
