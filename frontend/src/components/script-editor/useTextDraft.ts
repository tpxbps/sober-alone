import { useState, type SetStateAction } from "react";
import { useEditorStore } from "@/stores/editorStore";

export function useTextDraft<T>(step: string, source: string, initial: T) {
  const threadId = useEditorStore((state) => state.threadId);
  let hash = 2166136261;
  for (let i = 0; i < source.length; i++) hash = Math.imul(hash ^ source.charCodeAt(i), 16777619);
  const key = `editor-draft:${threadId}:${step}:${hash >>> 0}`;
  const read = (): T => {
    try { const saved = sessionStorage.getItem(key); return saved ? JSON.parse(saved) as T : initial; }
    catch { return initial; }
  };
  const [draft, setDraft] = useState(() => ({ key, value: read() }));
  const value = draft.key === key ? draft.value : read();
  const setValue = (next: SetStateAction<T>) => {
    const resolved = typeof next === 'function' ? (next as (old: T) => T)(value) : next;
    try { sessionStorage.setItem(key, JSON.stringify(resolved)); } catch { /* storage may be unavailable */ }
    setDraft({ key, value: resolved });
  };
  return [value, setValue] as const;
}
