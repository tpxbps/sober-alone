import { useState, useCallback, useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useSearchParams } from 'react-router-dom';

import { Homepage } from '@/screens/Homepage';
import { GamePage } from '@/screens/GamePage';
import { useGameStore } from '@/stores/gameStore';
import { gameApi } from '@/lib/api';
import { useBGM } from '@/hooks/useBGM';
import { initClickSound } from '@/lib/clickSound';

type AppScreen = 'home' | 'game';

// Storage keys
const STORAGE_KEY = 'sober_alone_session';

function App() {
  const [currentScreen, setCurrentScreen] = useState<AppScreen>('home');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isRestoring, setIsRestoring] = useState(false);

  const { reset, initializeGame } = useGameStore();
  const { playLobby, stop } = useBGM();
  const [searchParams, setSearchParams] = useSearchParams();

  // Initialize click sound effect (once)
  useEffect(() => {
    initClickSound();
  }, []);

  // Try to restore session from URL or localStorage on mount
  useEffect(() => {
    const restoreSession = async () => {
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
            setSessionId(sessionIdToRestore);
            setCurrentScreen('game');
            await initializeGame(sessionIdToRestore);
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

  // Play lobby BGM when on home screen
  useEffect(() => {
    if (currentScreen === 'home' && !isRestoring) {
      playLobby();
    }
  }, [currentScreen, isRestoring, playLobby]);

  // Handle starting a new game from homepage
  const handleStartGame = useCallback((newSessionId: string) => {
    stop(); // stop lobby BGM, GamePage will play stage BGM
    setSessionId(newSessionId);
    setCurrentScreen('game');
    // Update URL
    setSearchParams({ session: newSessionId });
    // Save to localStorage
    localStorage.setItem(STORAGE_KEY, newSessionId);
  }, [setSearchParams, stop]);

  // Handle exiting game
  const handleExitGame = useCallback(() => {
    const currentSessionId = sessionId;
    // 1. Immediately cancel all in-flight SSE streams and reset UI state
    const store = useGameStore.getState();
    store.cancelActiveOperations();

    // 2. Reset store state
    reset();
    setSessionId(null);
    setCurrentScreen('home');
    setSearchParams({});
    localStorage.removeItem(STORAGE_KEY);

    // 3. Fire-and-forget: notify backend to clean up resources
    if (currentSessionId) {
      gameApi.abandonSession(currentSessionId).catch(() => {
        // Silently ignore - backend cleanup is best-effort
      });
    }
  }, [sessionId, reset, setSearchParams]);

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
    <div className="min-h-screen bg-background text-foreground">
      <AnimatePresence mode="wait">
        {currentScreen === 'home' && (
          <motion.div
            key="home"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3 }}
          >
            <Homepage onStartGame={handleStartGame} />
          </motion.div>
        )}

        {currentScreen === 'game' && sessionId && (
          <motion.div
            key="game"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3 }}
          >
            <GamePage sessionId={sessionId} onExit={handleExitGame} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default App;
