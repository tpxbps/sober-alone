import { useCallback, useSyncExternalStore } from "react";

const readSessions = new Set<string>();
const eventName = "personal-script-read";

function subscribe(listener: () => void) {
  window.addEventListener("storage", listener);
  window.addEventListener(eventName, listener);
  return () => {
    window.removeEventListener("storage", listener);
    window.removeEventListener(eventName, listener);
  };
}

export function usePersonalScriptRead(sessionId?: string) {
  const read = useSyncExternalStore(subscribe, () => {
    if (!sessionId) return false;
    try {
      return readSessions.has(sessionId) || localStorage.getItem(`script_opened_${sessionId}`) === "true";
    } catch {
      return readSessions.has(sessionId);
    }
  }, () => false);
  const markRead = useCallback(() => {
    if (!sessionId) return;
    readSessions.add(sessionId);
    try {
      localStorage.setItem(`script_opened_${sessionId}`, "true");
    } catch { /* The in-memory record also works when storage is unavailable. */ }
    window.dispatchEvent(new Event(eventName));
  }, [sessionId]);
  return { read, markRead };
}
