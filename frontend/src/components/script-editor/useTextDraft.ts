import { useEffect, useState } from "react";
import { useEditorStore } from "@/stores/editorStore";

export function useTextDraft<T>(step: string, source: string, initial: T) {
  const threadId = useEditorStore((state) => state.threadId);
  let hash = 2166136261;
  for (let i = 0; i < source.length; i++) hash = Math.imul(hash ^ source.charCodeAt(i), 16777619);
  const key = `editor-draft:${threadId}:${step}:${hash >>> 0}`;
  const [value, setValue] = useState<T>(() => {
    try { const saved = sessionStorage.getItem(key); return saved ? JSON.parse(saved) as T : initial; }
    catch { return initial; }
  });
  useEffect(() => {
    try { sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* storage may be unavailable */ }
  }, [key, value]);
  return [value, setValue] as const;
}
