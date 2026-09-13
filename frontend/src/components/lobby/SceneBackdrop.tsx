export function SceneBackdrop({ screen }: { screen: 'home' | 'game' | 'editor' }) {
  return <div className="app-backdrops" data-scene={screen} aria-hidden="true">
    <img className="backdrop-home" src="/lobby/theatre.webp" alt="" />
    <img className="backdrop-game" src="/lobby/game.webp" alt="" />
    <img className="backdrop-editor" src="/lobby/workshop.webp" alt="" />
  </div>;
}
