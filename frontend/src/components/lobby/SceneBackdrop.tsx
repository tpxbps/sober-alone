import { useState } from 'react';
type Screen = 'home' | 'game' | 'editor';

export function SceneBackdrop({ screen }: { screen: Screen }) {
  const [ready, setReady] = useState<Screen[]>([]);
  const displayed = ready.includes(screen) ? screen : ready.at(-1) || screen;
  return <div className="app-backdrops" data-scene={displayed} aria-hidden="true">
    {[...new Set([...ready, screen])].map(scene => <img key={scene} className={`backdrop-${scene}`}
      src={`/lobby/${scene === 'home' ? 'theatre' : scene === 'editor' ? 'workshop' : 'game'}.webp`}
      decoding="async" fetchPriority="high" alt="" onLoad={event => {
        const element = event.currentTarget;
        void element.decode().then(() => {
          if (element.isConnected) setReady(previous => previous.includes(scene) ? previous : [...previous, scene]);
        }).catch(() => {});
      }} />)}
  </div>;
}
