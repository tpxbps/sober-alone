import { useEffect } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { useGameStore } from '@/stores/gameStore';
import { prefetchClueAssets } from '@/lib/clueImageLoader';

export function useCluePrefetch(sessionId: string) {
  const { urls, busy } = useGameStore(useShallow(state => ({
    urls: JSON.stringify(state.clueAssetPreload),
    busy: state.sessionId !== sessionId || state.isLoading || state.isStreaming
      || state.isProcessingReactions || state.isAdvancingStage
      || state.cluePresentation?.status === 'pending',
  })));
  useEffect(() => {
    if (busy) return;
    let cancel = () => {};
    const resume = () => {
      cancel();
      if (!document.hidden) cancel = prefetchClueAssets(JSON.parse(urls));
    };
    resume();
    document.addEventListener('visibilitychange', resume);
    return () => { cancel(); document.removeEventListener('visibilitychange', resume); };
  }, [sessionId, urls, busy]);
}
