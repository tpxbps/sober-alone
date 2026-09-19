import { useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import * as Dialog from '@radix-ui/react-dialog';
import { ArrowRight, Pause, Play, SkipForward, RotateCcw } from 'lucide-react';
import type { ClueMedia, CluePresentationState } from '@/types/cluePresentation';
import { audioPlayerManager } from '@/lib/audioPlayerManager';
import { ClueEvidenceList } from './ClueEvidenceList';
import { ImmersiveClueScene } from './ImmersiveClueScene';
import { warmCluePresentation } from '@/lib/clueImageLoader';
import './cluePresentation.css';
import './immersiveClueScene.css';

function Highlight({ text, emphasis }: { text: string; emphasis?: string }) {
  if (!emphasis || !text.includes(emphasis)) return <>{text}</>;
  const index = text.indexOf(emphasis);
  return <>{text.slice(0, index)}<mark>{emphasis}</mark>{text.slice(index + emphasis.length)}</>;
}

function SceneImage({ media, index, motionName, duration, paused }: {
  media: ClueMedia; index: number; motionName: string; duration: number; paused: boolean;
}) {
  const [failed, setFailed] = useState(false);
  if (failed) return <div className="cinema-image-unavailable">图片暂不可用 · 线索文字仍可查看</div>;
  return <div className={`cinema-art cinema-art-${motionName}`} style={{ animationDelay: `${index * 160}ms`, animationPlayState: paused ? 'paused' : 'running' }}>
    <img draggable={false} src={media.image_url} alt={media.alt} onError={() => setFailed(true)} decoding="async"
      style={{
        '--focus': `${media.focus[0] * 100}% ${media.focus[1] * 100}%`,
        '--mobile-focus': `${(media.mobile_focus ?? media.focus)[0] * 100}% ${(media.mobile_focus ?? media.focus)[1] * 100}%`,
        animationDuration: `${duration}ms`, animationPlayState: paused ? 'paused' : 'running',
      } as React.CSSProperties} />
  </div>;
}

export function CluePresentationOverlay({ state, onContinue }: {
  state: CluePresentationState; onContinue: () => Promise<void>;
}) {
  const reduced = useReducedMotion();
  const presentation = state.presentation;
  const valid = (presentation?.version === 1 || presentation?.version === 2) && presentation.status === 'ready'
    && Array.isArray(presentation.shots) && presentation.shots.length > 0
    && presentation.shots.every(shot => shot && Number.isFinite(shot.duration_ms) && shot.duration_ms >= 1000
      && shot.duration_ms <= 15000 && typeof shot.title === 'string' && typeof shot.caption === 'string'
      && Array.isArray(shot.clue_ids) && Array.isArray(shot.labels))
    && presentation.shots.reduce((sum, shot) => sum + shot.duration_ms, 0) <= 90000;
  const shots = useMemo(() => valid ? presentation.shots : [], [valid, presentation]);
  const total = shots.reduce((sum, shot) => sum + shot.duration_ms, 0);
  const [elapsed, setElapsed] = useState(0);
  const [paused, setPaused] = useState(false);
  const [hidden, setHidden] = useState(() => document.hidden);
  const [loaded, setLoaded] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [allImagesFailed, setAllImagesFailed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const continuing = useRef(false);
  const finished = !valid || Boolean(reduced) || allImagesFailed || elapsed >= total;
  const stopped = paused || hidden || !loaded || finished;
  let start = 0;
  let index = 0;
  while (index < shots.length - 1 && elapsed >= start + shots[index].duration_ms) start += shots[index++].duration_ms;
  const shot = shots[index];
  const clueMap = useMemo(() => new Map((state.reference_clues ?? state.clues).map(clue => [clue.id, clue])), [state.clues, state.reference_clues]);
  const art = (shot?.clue_ids ?? []).map(id => clueMap.get(id)?.media).filter((media): media is ClueMedia => media?.status === 'ready');
  const sequence = art.length > 1 && !['split', 'chain'].includes(shot?.motion ?? '');
  const currentArt = sequence
    ? [art[Math.min(art.length - 1, Math.floor((elapsed - start) / shot.duration_ms * art.length))]]
    : art.length ? art : presentation?.background ? [presentation.background] : [];

  useEffect(() => {
    audioPlayerManager.stop();
    const change = () => setHidden(document.hidden);
    document.addEventListener('visibilitychange', change);
    return () => document.removeEventListener('visibilitychange', change);
  }, []);
  useEffect(() => {
    if (!valid || reduced) return;
    let active = true;
    const timeout = window.setTimeout(() => { if (active) { active = false; setAllImagesFailed(true); } }, 12000);
    void warmCluePresentation(state, loadAttempt > 0).then(results => {
      if (active) {
        clearTimeout(timeout);
        const ready = results.length > 0 && results.every(Boolean);
        setLoaded(ready);
        setAllImagesFailed(!ready);
      }
    });
    return () => { active = false; clearTimeout(timeout); };
    // Polling creates equivalent state objects; it must not restart the readiness deadline.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.presentation_id, valid, reduced, loadAttempt]);
  useEffect(() => {
    if (stopped) return;
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const delta = now - last;
      if (delta >= 15) { setElapsed(value => Math.min(total, value + Math.min(delta, 150))); last = now; }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [stopped, total]);
  const confirm = async () => {
    if (!finished || continuing.current) return;
    continuing.current = true; setSubmitting(true); setError('');
    try { await onContinue(); }
    catch { setError('暂时无法确认，请重试。你的线索和进度已保留。'); }
    finally { continuing.current = false; setSubmitting(false); }
  };

  return <Dialog.Root open><Dialog.Portal>
    <Dialog.Overlay className="fixed inset-0 z-[110] bg-black" />
    <Dialog.Content aria-describedby="clue-cinema-description" onEscapeKeyDown={event => event.preventDefault()}
      onPointerDownOutside={event => event.preventDefault()} className={`clue-cinema ${!finished ? 'is-playing' : ''} ${presentation?.template === 'dossier' ? 'is-dossier' : ''} ${presentation?.version === 2 && !finished ? 'is-immersive' : ''} ${reduced ? 'is-reduced' : ''} ${stopped ? 'is-paused' : ''}`}
      onDragStart={event => { if (!finished) event.preventDefault(); }}
      onClick={event => { if (event.target === event.currentTarget && finished) void confirm(); }}>
      <div className="cinema-backdrop" aria-hidden="true" style={loaded && presentation?.background ? {
        backgroundImage: `url("${presentation.background.image_url}")`,
        ...(presentation.version === 2 && !finished ? { transform: `scale(${1.06 + elapsed / Math.max(total, 1) * 0.12}) translateX(${elapsed / Math.max(total, 1) * 1.5 - 1}%)` } : {}),
      } : undefined} />
      <div className="cinema-shade" aria-hidden="true" />
      <header className="cinema-header">
        <div><p className="cinema-eyebrow">第 {String(state.round).padStart(2, '0')} 轮 · 公开线索</p><Dialog.Title>{presentation?.title ?? '新的线索已送达'}</Dialog.Title></div>
        {!finished && <div className="cinema-controls"><button type="button" onClick={() => setPaused(!paused)} aria-label={paused ? '继续播放' : '暂停演出'}>{paused ? <Play /> : <Pause />}</button><button type="button" onClick={() => setElapsed(total)}><SkipForward /><span>跳至结尾</span></button></div>}
      </header>
      <Dialog.Description id="clue-cinema-description" className="sr-only">观看本轮线索演出。可以暂停或跳至结尾，完成后确认继续推理。</Dialog.Description>
      {!finished ? <>
        {!loaded ? <div className="cinema-loading" role="status">正在准备本轮演出…</div> : presentation?.version === 2
          ? <ImmersiveClueScene presentation={presentation} clues={state.reference_clues ?? state.clues} elapsed={elapsed} duration={total} />
          : <AnimatePresence mode="wait">
          <motion.main key={shot.id} className={`cinema-scene scene-${shot.motion}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.22 }}>
            <div className={`cinema-pictures ${currentArt.length > 1 ? 'is-split' : ''}`}>
              {currentArt.map((media, i) => <SceneImage key={media.image_url} media={media} index={i} motionName={shot.motion} duration={shot.duration_ms} paused={stopped} />)}
              <div className="cinema-picture-vignette" />
            </div>
            <div className="cinema-copy">
              <p className="cinema-shot-number">{String(index + 1).padStart(2, '0')} / {String(shots.length).padStart(2, '0')}</p>
              <h2>{shot.title}</h2><p className="cinema-caption"><Highlight text={shot.caption} emphasis={shot.emphasis} /></p>
              {shot.labels.length > 0 && <ol className={`cinema-labels ${shot.motion === 'chain' ? 'is-chain' : ''}`}>
                {shot.labels.map((label, i) => <li key={i} style={{ animationDelay: `${i * 550}ms`, animationPlayState: stopped ? 'paused' : 'running' }}><span>{label}</span>{i < shot.labels.length - 1 && shot.motion === 'chain' && <svg viewBox="0 0 44 12" aria-hidden="true"><path d="M0 6H40M34 1L40 6L34 11" /></svg>}</li>)}
              </ol>}
            </div>
          </motion.main>
        </AnimatePresence>}
      </> : <main className="cinema-end">
        <p className="cinema-eyebrow">{state.clues.length} 条线索已公开</p><h2>接下来，听听彼此的解释。</h2>
        <p className="cinema-end-intro">可以展开回看完整线索。准备好后，再开始本轮推理。</p>
        {allImagesFailed && <p className="cinema-end-intro">图片尚未全部就绪，可以先阅读线索，或重试加载演出。</p>}
        <ClueEvidenceList clues={state.clues} />
        {error && <p role="alert" className="cinema-error">{error}</p>}
        <div className="cinema-end-actions">{valid && !reduced && <button type="button" className="cinema-replay" onClick={() => {
          setElapsed(0); setPaused(false);
          if (allImagesFailed) { setAllImagesFailed(false); setLoaded(false); setLoadAttempt(value => value + 1); }
        }}><RotateCcw />{allImagesFailed ? '重试加载演出' : '再看一遍'}</button>}<button type="button" className="cinema-continue" disabled={submitting} onClick={() => void confirm()}>{submitting ? '正在进入…' : '继续推理'}<ArrowRight /></button></div>
      </main>}
    </Dialog.Content>
  </Dialog.Portal></Dialog.Root>;
}
