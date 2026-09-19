import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { editorApi } from "@/lib/editorApi";
import { useEditorStore } from "@/stores/editorStore";
import type { OutlineCommand } from "@/types/outline";

export function useOutlineSession(threadId: string | null) {
  const progress = useEditorStore(s => s.outlineProgress);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const requestInFlight = useRef<string | null>(null);
  const refresh = useCallback(async () => {
    if (!threadId || useEditorStore.getState().threadId !== threadId) return;
    await useEditorStore.getState().fetchState();
  }, [threadId]);
  useEffect(() => {
    if (!useEditorStore.getState().operationId) void refresh();
  }, [refresh]);

  const act = useCallback(async (command: Omit<OutlineCommand, "request_id" | "expected_revision">) => {
    if (!threadId || requestInFlight.current) return false;
    setBusy(true);
    setError("");
    const latest = useEditorStore.getState().outlineProgress;
    const request: OutlineCommand = {
      ...command, request_id: crypto.randomUUID(),
      expected_revision: latest?.control.revision || latest?.revision ||
        useEditorStore.getState().workflowState?.outline_session?.revision || 1,
    };
    requestInFlight.current = request.request_id;
    try {
      let accepted;
      try { accepted = await editorApi.outlineAction(threadId, request); }
      catch (err) {
        if (axios.isAxiosError(err) && !err.response) accepted = await editorApi.outlineAction(threadId, request);
        else throw err;
      }
      requestInFlight.current = null;
      setBusy(false);
      // The durable operation owns SSE and disconnected recovery for all stages.
      return await useEditorStore.getState().followOutlineOperation(accepted.operation_id);
    } catch (err) {
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null;
      setError(typeof detail === "string" ? detail : err instanceof Error ? err.message : "操作未完成，请重试");
      void refresh();
      return false;
    } finally {
      if (requestInFlight.current === request.request_id) {
        requestInFlight.current = null;
        setBusy(false);
      }
    }
  }, [threadId, refresh]);
  return { progress, error, busy, act, refresh };
}
