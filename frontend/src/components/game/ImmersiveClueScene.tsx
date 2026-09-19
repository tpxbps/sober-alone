import { useMemo, useSyncExternalStore, type CSSProperties } from 'react';
import type { ClueMedia, CluePresentation, ClueShot } from '@/types/cluePresentation';
import type { PublicClue } from '@/types/game';
import { clueGatherLayout } from '@/lib/clueGatherLayout';

const clamp = (value: number) => Math.min(1, Math.max(0, value));
const ease = (value: number) => 1 - Math.pow(1 - clamp(value), 3);
const smooth = (value: number) => { const t = clamp(value); return t * t * (3 - 2 * t); };
const mix = (a: number, b: number, value: number) => a + (b - a) * value;
const berths = [[-35, -19], [35, -17], [-34, 17], [34, 19], [-9, -28], [10, 24], [0, -8]];
const smallScreen = () => window.matchMedia('(max-width: 700px)').matches;
const subscribe = (listener: () => void) => {
  const query = window.matchMedia('(max-width: 700px)');
  query.addEventListener('change', listener);
  return () => query.removeEventListener('change', listener);
};

/** One playhead owns the camera, optical reveal, focus and final gathering. */
export function ImmersiveClueScene({ presentation, clues, elapsed, duration }: {
  presentation: CluePresentation; clues: PublicClue[]; elapsed: number; duration: number;
}) {
  const mobile = useSyncExternalStore(subscribe, smallScreen, () => false);
  const { tracks, cues } = useMemo(() => {
    const map = new Map(clues.map(clue => [clue.id, clue]));
    const entries: { id: string; media: ClueMedia; at: number; span: number;
      composition?: ClueShot['composition']; position: number; count: number }[] = [];
    const cues = presentation.shots.map((shot, shotIndex) => {
      const at = presentation.shots.slice(0, shotIndex).reduce((sum, cue) => sum + cue.duration_ms, 0);
      const slot = shot.duration_ms / Math.max(1, shot.clue_ids.length);
      for (const [index, id] of shot.clue_ids.entries()) {
        const clue = map.get(id);
        if (clue?.media?.status === 'ready') entries.push({
          id: shot.id + id, media: clue.media,
          at: at + index * (shot.composition === 'pair' ? 240 : slot),
          span: shot.composition === 'pair' ? shot.duration_ms - index * 240 : slot,
          composition: shot.composition, position: index, count: shot.clue_ids.length,
        });
      }
      return { ...shot, at };
    });
    return { tracks: entries, cues };
  }, [presentation, clues]);
  const progress = clamp(elapsed / duration);
  const gatherAt = duration - Math.min(2300, duration * 0.2);
  const assemble = smooth((elapsed - gatherAt) / 1800);
  const dossier = presentation.template === 'dossier';
  const shot = cues.find(cue => elapsed < cue.at + cue.duration_ms) ?? cues.at(-1)!;
  // The photographs can gather early, but the preceding caption must finish in place.
  const closingCue = cues.length > 1 && !cues.at(-1)!.clue_ids.length ? cues.at(-1) : undefined;
  const phase = closingCue && elapsed >= closingCue.at ? 'gather'
    : elapsed < (tracks[0]?.at ?? duration) ? 'opening' : 'evidence';
  const copyAge = elapsed - shot.at;
  const copyOpacity = Math.min(ease(copyAge / 650), ease((shot.duration_ms - copyAge) / 360));

  const light = shot.composition === 'light' ? Math.sin(clamp(copyAge / shot.duration_ms) * Math.PI) ** 2 : 0;
  return <main className="cinema-immersive" data-scene={shot.id} data-phase={phase} data-gathered={assemble >= 0.995} data-preset={presentation.visual_preset}>
    <div className="cinema-space" aria-hidden="true"
      style={{ transform: `perspective(1800px) rotateY(${Math.sin(progress * Math.PI) * 1.2}deg) scale(${1 + progress * 0.025})` }}>
      {tracks.map((track, index) => {
        const age = elapsed - track.at;
        const arrival = smooth(age / 1000);
        const departure = smooth((age - track.span * 0.76) / 1550);
        const drift = clamp(age / (track.span + 1500));
        const side = index % 2 === 0 ? -1 : 1;
        const variant = index % 3;
        const berth = berths[index % berths.length];
        // Alternating wide, off-axis and close compositions; no repeated flying-card entrance.
        const paired = track.composition === 'pair';
        const pairPosition = track.position - (track.count - 1) / 2;
        const heroX = paired ? (mobile ? side * 6 : pairPosition * (track.count > 2 ? 28 : 42))
          : track.composition === 'pan' ? mix(-12, 12, drift)
          : mobile ? side * 3 : variant === 1 ? side * 13 : side * 4;
        const heroY = paired && mobile ? pairPosition * (track.count > 2 ? 15 : 23)
          : mobile ? -5 : variant === 2 ? -4 : 0;
        const x = mix(heroX + side * (1 - arrival) * 9, berth[0], departure);
        const y = mix(heroY + (dossier ? 9 : 2) * (1 - arrival), berth[1], departure);
        const gather = clueGatherLayout(index, tracks.length, mobile);
        const heroScale = paired ? (track.count > 2 ? 0.43 : 0.59) : 1;
        const scale = mix(mix(1.025, 0.985, drift) * heroScale, mobile ? 0.28 : 0.3, departure);
        const angle = mix(dossier ? side * 2.5 * (1 - arrival) : 0, side * (4 + index % 3), departure);
        const insetX = !paired && variant === 1 && !mobile ? 13 : 0;
        const insetY = !paired && variant === 2 && !mobile ? 8 : 0;
        const occluded = track.composition === 'occlusion';
        const reveal = (1 - arrival) * (occluded ? 92 : dossier ? 48 : 42);
        const crop = 1 - Math.max(departure, assemble);
        const opacity = age < 0 ? 0 : ease(age / 700) * mix(1, 0.22, departure);
        const focus = track.media.focus;
        const phoneFocus = track.media.mobile_focus ?? focus;
        const style = {
          transform: `translate3d(calc(-50% + ${mix(x, gather.x, assemble)}vw), calc(-50% + ${mix(y, gather.y, assemble)}vh), ${mix(-90 * (1 - arrival), -220, departure) * (1 - assemble)}px) rotateX(${dossier ? (1 - arrival) * 9 * (1 - assemble) : 0}deg) rotateY(${side * (1 - arrival) * 6 * (1 - assemble)}deg) rotate(${mix(angle, gather.angle, assemble)}deg) scale(${mix(scale, gather.scale, assemble)})`,
          opacity: mix(opacity, age >= 0 ? 1 : 0, assemble),
          zIndex: age >= 0 && departure < 0.8 ? 20 + index : index + 1,
          filter: `brightness(${mix(mix(0.78, 1, arrival), 0.82, departure)})`,
          clipPath: `inset(${(insetY + (dossier && !occluded ? reveal : 0)) * crop}% ${(insetX + (!dossier || occluded ? reveal : 0)) * crop}% ${insetY * crop}% ${insetX * crop}%)`,
          '--focus': `${focus[0] * 100}% ${focus[1] * 100}%`,
          '--mobile-focus': `${phoneFocus[0] * 100}% ${phoneFocus[1] * 100}%`,
          '--edge-opacity': Math.max(departure * 0.3, assemble * 0.65),
        } as CSSProperties;
        const lens = {
          transform: `scale(${mix(mix(track.composition === 'detail' ? 1.42 : variant === 2 ? 1.3 : 1.14, 1.02, drift), 1, assemble)}) translate3d(${side * mix(2.8, -1.8, drift) * (1 - assemble)}%, ${mix(1.5, -1.5, drift) * (1 - assemble)}%, 0)`,
        };
        return <div key={track.id} className="cinema-card" data-active={age >= 0 && departure < 0.8} style={style}>
          <FilmImage media={track.media} style={lens} />
          <div className="cinema-card-wash" style={{ opacity: 1 - assemble * 0.75 }} />
          <div className="cinema-card-edge" />
        </div>;
      })}
    </div>
    <div className="cinema-optical-shade" aria-hidden="true" />
    {presentation.visual_preset === 'cold-occlusion' && <div className="cinema-curtain" aria-hidden="true"
      style={{ transform: `translateX(${mix(-7, -25, ease(elapsed / 4200))}%)`, opacity: 1 - assemble }} />}
    {light > 0 && <div className="cinema-light-return" aria-hidden="true" style={{ opacity: light * 0.18 }} />}
    <div className="cinema-film-grain" aria-hidden="true" />
    <div className="cinema-iris" aria-hidden="true" style={{ opacity: Math.max(0, 1 - elapsed / 1100) }} />
    <div className="cinema-copy" style={{ opacity: copyOpacity, transform: `translateY(${(1 - ease(copyAge / 900)) * 14}px)` }}>
      <h2>{shot.title}</h2>
      {shot.caption && <p className="cinema-caption">{shot.caption}</p>}
    </div>
  </main>;
}

function FilmImage({ media, style }: { media: ClueMedia; style: CSSProperties }) {
  return <img draggable={false} src={media.image_url} alt="" decoding="async" style={style}
    onError={event => { event.currentTarget.style.visibility = 'hidden'; }} />;
}
