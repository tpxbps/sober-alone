import { useState, useCallback, useEffect, lazy, Suspense } from 'react';
import { useReducedMotion } from 'framer-motion';
import { flushSync } from 'react-dom';
import { useSearchParams } from 'react-router-dom';

import { Homepage } from '@/screens/Homepage';
import { useSettingsStore } from '@/stores/settingsStore';
import { useGameStore } from '@/stores/gameStore';
import { hasStoredEditorSession } from '@/stores/editorStore';
import { gameApi } from '@/lib/api';
import { SceneBackdrop } from '@/components/lobby/SceneBackdrop';
import { transitionScene } from '@/lib/sceneTransition';

type AppScreen = 'home' | 'game' | 'editor';
const GamePage = lazy(() => import('@/screens/GamePage').then(module => ({ default: module.GamePage })));
const ScriptEditorPage = lazy(() => import('@/screens/ScriptEditorPage').then(module => ({ default: module.ScriptEditorPage })));

// Storage keys
const STORAGE_KEY = 'sober_alone_session';

function App() {
  const [currentScreen, setCurrentScreen] = useState<AppScreen>('home');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [editScriptId, setEditScriptId] = useState<string | null>(null);
  const [isRestoring, setIsRestoring] = useState(false);
  const [entering, setEntering] = useState(false);
  const reducedMotion = useReducedMotion();
  const lobbyMotionEnabled = useSettingsStore(state => state.lobbyMotionEnabled);
  const quiet = Boolean(reducedMotion) || !lobbyMotionEnabled;
  useEffect(() => {
    if (!entering) return;
    const timer = setTimeout(() => setEntering(false), 350);
    return () => clearTimeout(timer);
  }, [entering]);

  const { reset, initializeGame } = useGameStore();
  const [searchParams, setSearchParams] = useSearchParams();

  // Try to restore session from URL or localStorage on mount
  useEffect(() => {
    const restoreSession = async () => {
      const editorTarget = searchParams.get('editor');
      if (editorTarget) {
        const requestedEditId = editorTarget.startsWith('edit:')
          ? editorTarget.slice('edit:'.length)
          : null;
        // Once a thread has been accepted, always resume that durable thread.
        // This prevents a refresh from starting a duplicate edit workflow.
        setEditScriptId(hasStoredEditorSession() ? null : requestedEditId);
        setCurrentScreen('editor');
        return;
      }

      // First check URL params
      const urlSessionId = searchParams.get('session');

      // Then check localStorage
      const storedSession = localStorage.getItem(STORAGE_KEY);

      const sessionIdToRestore = urlSessionId || storedSession;

      if (sessionIdToRestore) {
        setIsRestoring(true);
        try {
          // Verify session is still valid
          const state = await gameApi.getGameState(sessionIdToRestore);

          if (state.success && state.status !== 'completed') {
            // Session is valid, not finished - restore it
            if (!await initializeGame(sessionIdToRestore)) throw new Error('Game initialization failed');
            setSessionId(sessionIdToRestore);
            setCurrentScreen('game');
          } else {
            // Session invalid or finished - clear it
            localStorage.removeItem(STORAGE_KEY);
            setSearchParams({});
          }
        } catch (error) {
          console.error('Failed to restore session:', error);
          localStorage.removeItem(STORAGE_KEY);
          setSearchParams({});
        } finally {
          setIsRestoring(false);
        }
      }
    };

    restoreSession();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Handle starting a new game from homepage
  const handleStartGame = useCallback((newSessionId: string) => {
    setEntering(true);
    setSessionId(newSessionId);
    setCurrentScreen('game');
    window.scrollTo({ top: 0, behavior: 'instant' });
    // Update URL
    setSearchParams({ session: newSessionId });
    // Save to localStorage
    localStorage.setItem(STORAGE_KEY, newSessionId);
  }, [setSearchParams]);

  // Handle opening script editor
  const handleOpenEditor = useCallback((scriptId?: string) => {
    void transitionScene(() => {
      flushSync(() => {
        setEditScriptId(scriptId || null);
        setCurrentScreen('editor');
        setSearchParams({ editor: scriptId ? `edit:${scriptId}` : 'resume' });
      });
      window.scrollTo({ top: 0, behavior: 'instant' });
    }, quiet);
  }, [setSearchParams, quiet]);

  // Handle exiting editor back to home
  const handleExitEditor = useCallback(() => {
    void transitionScene(() => {
      flushSync(() => { setEditScriptId(null); setCurrentScreen('home'); setSearchParams({}); });
      window.scrollTo({ top: 0, behavior: 'instant' });
    }, quiet);
  }, [setSearchParams, quiet]);

  // Handle exiting game
  const handleExitGame = useCallback(() => {
    const currentSessionId = sessionId;
    // 1. Immediately cancel all in-flight SSE streams and reset UI state
    const store = useGameStore.getState();
    store.cancelActiveOperations();

    // 2. Reset store state
    void transitionScene(() => {
      flushSync(() => {
        reset(); setSessionId(null); setCurrentScreen('home'); setSearchParams({});
        localStorage.removeItem(STORAGE_KEY);
      });
      window.scrollTo({ top: 0, behavior: 'instant' });
    }, quiet);

    // 3. Fire-and-forget: notify backend to clean up resources
    if (currentSessionId) {
      gameApi.abandonSession(currentSessionId).catch(() => {
        // Silently ignore - backend cleanup is best-effort
      });
    }
  }, [sessionId, reset, setSearchParams, quiet]);

  // Show loading state while restoring
  if (isRestoring) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-center">
          <div className="w-12 h-12 border-2 border-primary border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-muted-foreground">恢复游戏中...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell min-h-screen text-foreground" data-quiet={quiet || undefined}>
      <SceneBackdrop screen={currentScreen} />
      <div className="app-screen">
        <Suspense fallback={<div role="status" aria-busy="true" className="flex min-h-[60vh] items-center justify-center gap-3 text-muted-foreground"><span className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />正在打开…</div>}>
        {currentScreen === 'home' && (
          <div key="home">
            <Homepage onStartGame={handleStartGame} onOpenEditor={handleOpenEditor} />
          </div>
        )}

        {currentScreen === 'game' && sessionId && (
          <div key="game">
            <GamePage sessionId={sessionId} onExit={handleExitGame} />
          </div>
        )}

        {currentScreen === 'editor' && (
          <div key="editor">
            <ScriptEditorPage onBack={handleExitEditor} editScriptId={editScriptId} />
          </div>
        )}
        </Suspense>
      </div>
      {entering && currentScreen === 'game' && <div aria-hidden="true" className={"game-entry-overlay game-entry-arrival" + (reducedMotion || !lobbyMotionEnabled ? " is-quiet" : "")} />}
    </div>
  );
}

export default App;
