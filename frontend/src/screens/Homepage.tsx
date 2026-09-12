import { useState, useEffect, useRef, useCallback } from "react";
import { AnimatePresence, motion, useAnimationControls, useReducedMotion } from "framer-motion";
import { flushSync } from "react-dom";
import { Github, Settings, RefreshCw, PenTool, ArrowRight, BookOpen } from "lucide-react";
import { scriptApi, systemApi } from "@/lib/api";
import { ScriptCard } from "@/components/game/ScriptCard";
import { ScriptSetup } from "@/components/lobby/ScriptSetup";
import { LobbyAtmosphere } from "@/components/lobby/LobbyAtmosphere";
import { SettingsModal } from "@/components/SettingsModal";
import { BookIcon } from "@/components/ui/BookIcon";
import { useSettingsStore } from "@/stores/settingsStore";
import type { Script } from "@/types/game";
import "@/components/lobby/lobby.css";

interface HomepageProps {
  onStartGame: (sessionId: string) => void;
  onOpenEditor: (scriptId?: string) => void;
}
const difficultyLabels: Record<number, string> = { 1: "简单", 2: "中等", 3: "困难", 4: "极难" };

export function Homepage({ onStartGame, onOpenEditor }: HomepageProps) {
  const [scripts, setScripts] = useState<Script[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedScript, setSelectedScript] = useState<Script | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [busy, setBusy] = useState(false);
  const [transitioning, setTransitioning] = useState(false);
  const sceneControls = useAnimationControls();
  const sceneVersion = useRef(0);
  useEffect(() => () => { sceneVersion.current += 1; }, []);
  const motionEnabled = useSettingsStore(state => state.lobbyMotionEnabled);
  const reducedMotion = useReducedMotion();
  const quiet = !motionEnabled || Boolean(reducedMotion);
  const version = useRef(0);
  const setupAnchor = useRef<HTMLDivElement>(null);
  const previousCard = useRef<{ element: HTMLElement; top: number } | null>(null);
  const loadScripts = useCallback(async () => {
    const request = ++version.current;
    setIsLoading(true); setError(null);
    try {
      const response = await scriptApi.listScripts();
      if (request !== version.current) return;
      if (!response.success || !Array.isArray(response.scripts)) throw new Error("Invalid script list");
      setScripts(response.scripts);
    } catch { if (request === version.current) setError("加载剧本失败，请稍后重试。"); }
    finally { if (request === version.current) setIsLoading(false); }
  }, []);
  useEffect(() => {
    void loadScripts();
    void systemApi.getModelHealth().catch(() => {});
    return () => { version.current += 1; };
  }, [loadScripts]);
  const switchScene = async (script: Script | null, keyboard = false) => {
    if (busy) return;
    const ticket = ++sceneVersion.current;
    setTransitioning(true);
    if (!quiet) await sceneControls.start({ opacity: 0, y: 6, transition: { duration: .12 } });
    if (ticket !== sceneVersion.current) return;
    flushSync(() => setSelectedScript(script));
    if (script) {
      const anchor = setupAnchor.current;
      const headerHeight = document.querySelector(".lobby-header")?.getBoundingClientRect().height || 80;
      if (anchor) window.scrollTo({ top: window.scrollY + anchor.getBoundingClientRect().top - headerHeight - 24, behavior: "instant" });
      anchor?.querySelector<HTMLElement>("h1")?.focus({ preventScroll: true });
    } else {
      const previous = previousCard.current;
      if (previous?.element.isConnected) {
        window.scrollTo({ top: window.scrollY + previous.element.getBoundingClientRect().top - previous.top, behavior: "instant" });
        const target = keyboard ? previous.element.querySelector<HTMLElement>("[data-script-open]") : document.getElementById("script-list");
        target?.focus({ preventScroll: true });
      }
    }
    await sceneControls.start({ opacity: 1, y: 0, transition: { duration: quiet ? 0 : .32, ease: [.22, 1, .36, 1] } });
    if (ticket === sceneVersion.current) setTransitioning(false);
  };
  const selectScript = (script: Script) => {
    if (busy) return;
    const card = document.querySelector<HTMLElement>('[data-script-id="' + CSS.escape(script.script_id) + '"]');
    if (card) previousCard.current = { element: card, top: card.getBoundingClientRect().top };
    void switchScene(script);
  };
  const returnToList = (keyboard = false) => { void switchScene(null, keyboard); };
  const groups = scripts.reduce((result, script) => {
    const difficulty = script.difficulty || 1;
    (result[difficulty] ||= []).push(script);
    return result;
  }, {} as Record<number, Script[]>);
  return (
    <div className={`dream-lobby${quiet ? " is-still" : ""}${busy ? " is-entering" : ""}${transitioning ? " is-transitioning" : ""}`}>
      <LobbyAtmosphere quiet={quiet} paused={busy || showSettings} />
      <a inert={busy} className="lobby-skip" href="#script-list">跳到剧本列表</a>
      {/* Header */}
      <header inert={busy} className="lobby-header sticky top-0 z-40 border-b border-border/50 bg-background/80 backdrop-blur-xl">
        <div className="container mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            {/* Logo */}
            <div className="flex min-w-0 items-center gap-3">
              <BookIcon size={48} />
              <div>
                <h1 className="text-xl font-serif text-foreground" onDragStart={event => event.preventDefault()}>独醒</h1>
                <p className="text-xs text-muted-foreground">AI剧本杀</p>
              </div>

            </div>

            {/* Nav */}
            <nav className="flex items-center gap-2 sm:gap-3">
              <button aria-label="创作工坊"
                onClick={() => onOpenEditor()}
                className="relative flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 transition-colors text-sm font-medium"
              >
                <PenTool className="w-4 h-4" />
                <span className="hidden sm:inline">创作工坊</span>
                <span className="absolute -top-1.5 -right-1.5 px-1 py-0.5 rounded text-[9px] leading-none bg-primary text-primary-foreground">
                  Beta
                </span>
              </button>
              <a
                href="https://github.com/tpxbps/sober-alone"
                target="_blank"
                rel="noopener noreferrer"
                aria-label="在 GitHub 查看独醒开源项目"
                className="inline-flex items-center gap-1.5 rounded-lg border border-border/70 bg-secondary/35 px-2.5 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-primary/40 hover:bg-primary/10 hover:text-primary sm:px-3 sm:text-sm"
              >
                <Github className="h-4 w-4" />
                <span>开源仓库</span>
              </a>
              <button
                onClick={loadScripts}
                disabled={isLoading}
                className="p-2 rounded-lg hover:bg-secondary/50 transition-colors"
                title="刷新剧本" aria-label="刷新剧本"
              >
                <RefreshCw
                  className={`w-5 h-5 ${isLoading ? "animate-spin" : ""}`}
                />
              </button>
              <button
                onClick={() => setShowSettings(true)}
                className="p-2 rounded-lg hover:bg-secondary/50 transition-colors"
                title="设置" aria-label="设置"
              >
                <Settings className="w-5 h-5" />
              </button>
            </nav>
          </div>
        </div>
      </header>

      <motion.main initial={false} animate={sceneControls} className="lobby-main container mx-auto px-6">
        <div ref={setupAnchor} className="setup-anchor">
          {selectedScript && <ScriptSetup key={selectedScript.script_id} script={selectedScript} quiet={quiet} onBack={returnToList} onStartGame={onStartGame} onBusyChange={setBusy} />}
        </div>
        {!selectedScript && <div className="lobby-heading"><h1>剧本大厅</h1><p>选择一部剧本，开始你的故事</p></div>}
        <section tabIndex={-1} inert={busy} id="script-list" className="lobby-catalog" aria-label="剧本大厅" aria-busy={isLoading}>
          {error && <div role="alert" className="lobby-status">{error}<button onClick={loadScripts}>重试</button></div>}
          {isLoading && !scripts.length && <p className="lobby-status" role="status">加载剧本中…</p>}
          {Object.entries(groups).sort(([a], [b]) => Number(a) - Number(b)).map(([difficulty, stories]) =>
            <section key={difficulty} className="lobby-difficulty-group" aria-label={difficultyLabels[Number(difficulty)] || "其他剧本"}>
              <h2 className="lobby-group-title">{difficultyLabels[Number(difficulty)] || "其他剧本"}<span>{stories.length}</span></h2>
              <div className="lobby-catalog-grid">{stories.map(script =>
                <ScriptCard key={script.script_id} script={script} selected={script.script_id === selectedScript?.script_id} quiet={quiet} previewsEnabled={!busy && !showSettings} onClick={() => selectScript(script)} onDeleted={loadScripts} onEdit={() => onOpenEditor(script.script_id)} />
              )}</div>
            </section>
          )}
          {!isLoading && !error && !scripts.length && <div className="lobby-status"><BookOpen size={28} /><p>暂无剧本</p><button onClick={() => onOpenEditor()}>创作第一个故事</button></div>}
        </section>
        <button inert={busy} className="lobby-create-invitation" onClick={() => onOpenEditor()}><PenTool size={22} /><strong>更多故事，只等你落笔</strong><span>开始创作<ArrowRight size={17} /></span></button>
      </motion.main>
      <footer inert={busy} className="border-t border-border/30 py-6 text-center text-sm text-muted-foreground">© 2026 独醒 AI剧本杀</footer>

      <AnimatePresence>{showSettings && <SettingsModal onClose={() => setShowSettings(false)} onOwnershipClaimed={loadScripts} />}</AnimatePresence>
    </div>
  );
}
