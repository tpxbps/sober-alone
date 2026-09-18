import { useEffect, useRef, useState } from "react";
import { gameApi, scriptApi, systemApi, subscribeModelHealth } from "@/lib/api";
import { configuredModels } from "@/lib/capabilityAdapter";
import { assignModelsToAICharacters } from "@/lib/modelAssignment";
import { modelHealthMessage } from "@/lib/modelHealthPresentation";
import { useGameStore } from "@/stores/gameStore";
import type { AIModelOption, Character } from "@/types/game";
import type { ModelHealthItem, ModelHealthResponse } from "@/types/capabilities";

export function useScriptSetup(scriptId: string, quiet: boolean, onStartGame: (id: string) => void) {
  const [characters, setCharacters] = useState<Character[]>([]);
  const [models, setModels] = useState<AIModelOption[]>([]);
  const [health, setHealth] = useState<Record<string, ModelHealthItem>>({});
  const [human, setHuman] = useState<string | null>(null);
  const [assignments, setAssignments] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [modelReason, setModelReason] = useState("");
  const [healthMessage, setHealthMessage] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [reload, setReload] = useState(0);
  const [error, setError] = useState("");
  const [phase, setPhase] = useState<"idle" | "preparing" | "revealing">("idle");
  const alive = useRef(true);
  const creating = useRef(false);
  const pendingSession = useRef<string | null>(null);
  const committed = useRef(false);
  const deadline = useRef<ReturnType<typeof setTimeout> | null>(null);
  const finishWait = useRef<(() => void) | null>(null);

  useEffect(() => {
    alive.current = true;
    const background = new Image(); background.src = "/lobby/game.webp";
    return () => {
      alive.current = false;
      if (deadline.current) clearTimeout(deadline.current);
      finishWait.current?.();
      if (pendingSession.current && !committed.current) {
        void gameApi.abandonSession(pendingSession.current).catch(() => {});
        useGameStore.getState().reset();
      }
    };
  }, []);
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    setLoading(true); setLoadError(""); setModelReason("");
    setCharacters([]); setModels([]); setHuman(null); setAssignments({}); setHealth({});
    const applyHealth = (result: ModelHealthResponse) => {
      if (cancelled) return;
      setHealth(Object.fromEntries(result.models.map(item => [item.model, item])));
      setRefreshing(Boolean(result.probing));
      setHealthMessage(modelHealthMessage(result));
    };
    const unsubscribe = subscribeModelHealth(applyHealth);
    void systemApi.getModelHealth().then(applyHealth).catch(() => {});
    void Promise.allSettled([scriptApi.getScriptCharacters(scriptId, controller.signal), systemApi.getCapabilities()]).then(([characterResult, modelResult]) => {
      if (cancelled) return;
      if (characterResult.status === "fulfilled") {
        const chars = characterResult.value.characters?.filter(char => char.character_id && char.name) || [];
        setCharacters(chars);
        if (!chars.length) setLoadError("该剧本没有可用角色，请检查剧本数据后重试。");
      } else setLoadError("角色加载失败，请确认后端正常运行后重试。");
      if (modelResult.status === "fulfilled") {
        const available = configuredModels(modelResult.value);
        setModels(available);
        if (!available.length) setModelReason("暂未配置可用模型，请联系维护者。");
      } else setModelReason("无法读取模型配置，请稍后重新加载。");
      setLoading(false);
    });
    return () => { cancelled = true; controller.abort(); unsubscribe(); };
  }, [scriptId, reload]);
  useEffect(() => {
    if (!human || !models.length || creating.current) return;
    setAssignments(current => assignModelsToAICharacters({ characters, humanCharacterId: human, models, healthById: health, previous: current }));
  }, [characters, human, models, health]);
  const discardPending = () => {
    if (pendingSession.current) {
      void gameApi.abandonSession(pendingSession.current).catch(() => {});
      pendingSession.current = null;
      useGameStore.getState().reset();
    }
  };
  const selectHuman = (id: string) => {
    if (creating.current || human === id) return;
    discardPending(); setError(""); setHuman(id);
    setAssignments(assignModelsToAICharacters({ characters, humanCharacterId: id, models, healthById: health }));
  };
  const selectModel = (id: string, model: string) => {
    if (creating.current) return;
    discardPending(); setError("");
    setAssignments(current => ({ ...current, [id]: model }));
  };
  const refreshHealth = async () => {
    if (refreshing) return;
    setRefreshing(true); setHealthMessage("");
    try {
      const result = await systemApi.getModelHealth(true);
      if (!alive.current) return;
      setHealth(Object.fromEntries(result.models.map(item => [item.model, item])));
      setHealthMessage(modelHealthMessage(result, true));
    } catch { if (alive.current) setHealthMessage("测速失败，可继续使用当前配置"); }
    finally { if (alive.current) setRefreshing(false); }
  };
  const canStart = !loading && Boolean(human) && models.length > 0 &&
    characters.filter(char => char.character_id !== human).every(char => Boolean(assignments[char.character_id]) && models.some(model => model.id === assignments[char.character_id]));
  const wait = (ms: number) => new Promise<void>(resolve => {
    finishWait.current = resolve;
    deadline.current = setTimeout(() => { finishWait.current = null; resolve(); }, ms);
  });
  const start = async () => {
    if (!canStart || creating.current || !human) return;
    creating.current = true; setError(""); setPhase("preparing");
    const began = performance.now();
    try {
      if (!pendingSession.current) {
        const result = await gameApi.createGame({
          script_id: scriptId, human_character_id: human,
          ai_models: Object.fromEntries(Object.entries(assignments).filter(([id]) => id !== human)),
        });
        if (!result.success || !result.session_id) throw new Error(result.error || "创建游戏失败，请稍后重试。");
        if (!alive.current) { void gameApi.abandonSession(result.session_id).catch(() => {}); return; }
        pendingSession.current = result.session_id;
      }
      const ready = await useGameStore.getState().initializeGame(pendingSession.current);
      if (!alive.current) return;
      if (!ready) throw new Error("游戏资料暂未加载完成，请重试。已创建的会话会继续使用。");
      if (!quiet) {
        await wait(Math.max(0, 450 - (performance.now() - began)));
        if (!alive.current) return;
        setPhase("revealing"); await wait(300);
      }
      if (!alive.current) return;
      committed.current = true; onStartGame(pendingSession.current);
    } catch (reason) {
      if (alive.current) { setError(reason instanceof Error ? reason.message : "准备失败，请稍后重试。"); setPhase("idle"); }
    } finally { creating.current = false; }
  };
  return { characters, models, health, human, assignments, loading, loadError, modelReason,
    healthMessage, refreshing, error, phase, canStart, selectHuman, selectModel, refreshHealth, start,
    reload: () => { discardPending(); setError(""); setReload(value => value + 1); } };
}
