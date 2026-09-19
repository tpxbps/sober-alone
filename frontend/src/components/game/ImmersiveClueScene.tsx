import { useMemo } from 'react';
import type { ClueMedia, CluePresentation } from '@/types/cluePresentation';
import type { PublicClue } from '@/types/game';

const clamp = (value: number) => Math.min(1, Math.max(0, value));
const ease = (value: number) => 1 - Math.pow(1 - clamp(value), 3);
const mix = (a: number, b: number, value: number) => a + (b - a) * value;
const berths = [[-34, -19], [34, -17], [-32, 16], [33, 19], [-8, -26], [9, 23], [0, -8]];

/** All evidence stays in one continuous space; the playhead also owns every transform. */
export function ImmersiveClueScene({ presentation, clues, elapsed, duration }: {
  presentation: CluePresentation; clues: PublicClue[]; elapsed: number; duration: number;
}) {
  const tracks = useMemo(() => {
    const map = new Map(clues.map(clue => [clue.id, clue]));
    let start = 0;
    const entries: { id: string; media: ClueMedia; at: number; hold: number }[] = [];
    for (const shot of presentation.shots) {
      const slot = shot.duration_ms / Math.max(1, shot.clue_ids.length);
      for (const [index, id] of shot.clue_ids.entries()) {
        const clue = map.get(id);
        if (clue?.media?.status === 'ready') entries.push({
          id: shot.id + id, media: clue.media, at: start + index * slot,
          hold: Math.max(850, Math.min(1800, slot * 0.7)),
        });
      }
      start += shot.duration_ms;
    }
    return entries;
  }, [presentation, clues]);
  const progress = clamp(elapsed / duration);
  const assemble = ease((elapsed - duration + 2100) / 1800);
  const dossier = presentation.template === 'dossier';
  const currentIndex = tracks.reduce((active, track, index) => elapsed >= track.at ? index : active, -1);
  const shot = presentation.shots.find((_, index) => elapsed < presentation.shots.slice(0, index + 1)
    .reduce((sum, item) => sum + item.duration_ms, 0)) ?? presentation.shots.at(-1)!;

  return <main className="cinema-immersive" data-scene={shot.id}>
    <div className="cinema-space" aria-hidden="true"
      style={{ transform: `perspective(1500px) rotateX(${mix(2, -1, progress)}deg) rotateY(${Math.sin(progress * Math.PI * 2) * 2}deg) scale(${1 + progress * 0.075})` }}>
      <svg className="cinema-trace" viewBox="0 0 1000 700" preserveAspectRatio="none">
        <path d={dossier ? 'M-80 560 Q220 650 420 330 T1100 160' : 'M-80 620 C220 700 180 30 510 150 S790 690 1080 350'}
          pathLength="1" style={{ strokeDashoffset: 1 - progress }} />
      </svg>
      {tracks.map((track, index) => {
        const age = elapsed - track.at;
        const arrival = ease(age / 720);
        const departure = ease((age - track.hold) / 1250);
        const berth = berths[index % berths.length];
        const side = index % 2 === 0 ? -1 : 1;
        const x = mix(mix(side * (dossier ? 55 : 76), side * 4, arrival), berth[0], departure);
        const y = mix(mix(dossier ? 60 : side * 22, -3, arrival), berth[1], departure);
        const rotation = mix(mix(side * (dossier ? 35 : 18), side * -2, arrival), side * (7 + index % 3 * 3), departure);
        const float = Math.sin(elapsed / 1650 + index * 1.7) * 1.2 * departure;
        const scale = mix(mix(0.3, 0.91, arrival), 0.34, departure);
        const opacity = age < 0 ? 0 : clamp(age / 330) * mix(1, 0.58, departure);
        const position = {
          transform: `translate3d(calc(-50% + ${mix(x, (index - (tracks.length - 1) / 2) * 10.5, assemble)}vw), calc(-50% + ${mix(y + float, Math.abs(index - (tracks.length - 1) / 2) * 3.2 - 5, assemble)}vh), ${mix(mix(-650, 80, arrival), -160, departure)}px) rotateX(${dossier ? mix(38, 0, arrival) : 0}deg) rotateY(${mix(side * 26, 0, arrival)}deg) rotate(${mix(rotation, (index - (tracks.length - 1) / 2) * 6, assemble)}deg) scale(${mix(scale, 0.32, assemble)})`,
          opacity: mix(opacity, age >= 0 ? 0.88 : 0, assemble),
          zIndex: currentIndex === index ? 30 : index + 1,
          filter: `brightness(${mix(1, 0.76, departure)})`,
          '--reveal': `${(1 - arrival) * 100}%`,
        } as React.CSSProperties;
        return <div key={track.id} className="cinema-card" data-active={currentIndex === index} style={position}>
          <FilmImage media={track.media} />
          <div className="cinema-card-wash" />
          <span className="cinema-card-index">{String(index + 1).padStart(2, '0')}</span>
          <span className="cinema-card-edge" />
        </div>;
      })}
    </div>
    <div className="cinema-searchlight" aria-hidden="true"
      style={{ transform: `translateX(${mix(-65, 65, progress)}vw) rotate(-24deg)`, opacity: Math.sin(progress * Math.PI) * 0.22 }} />
    <div className="cinema-film-grain" aria-hidden="true" />
    <div className="cinema-iris" aria-hidden="true" style={{ opacity: Math.max(0, 1 - elapsed / 1300) }} />
    <div className="cinema-copy" key={shot.id}>
      <p className="cinema-shot-number">{dossier ? '纸页之间' : '暗处的回声'}</p>
      <h2>{shot.title}</h2>
      {shot.caption && <p className="cinema-caption">{shot.caption}</p>}
    </div>
  </main>;
}

function FilmImage({ media }: { media: ClueMedia }) {
  return <img src={media.image_url} alt="" decoding="async"
    onError={event => { event.currentTarget.style.visibility = 'hidden'; }}
    style={{
      '--focus': `${media.focus[0] * 100}% ${media.focus[1] * 100}%`,
      '--mobile-focus': `${(media.mobile_focus ?? media.focus)[0] * 100}% ${(media.mobile_focus ?? media.focus)[1] * 100}%`,
    } as React.CSSProperties} />;
}
