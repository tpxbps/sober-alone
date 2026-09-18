import { StrictMode, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import type { ClueStage } from '@/types/editor';
import type { CluePresentationState } from '@/types/cluePresentation';
import { CluePresentationOverlay } from '@/components/game/CluePresentationOverlay';
import { MentionComposer, type MentionComposerHandle } from '@/components/game/MentionComposer';
import { ClueDetails } from '@/components/game/ClueReferencePanel';
import { GameMessageMarkdown } from '@/components/ui/GameMessageMarkdown';
import { citedIds } from '@/lib/clueScope';
import '../index.css';

interface Preview { title?: string; clue_stages: ClueStage[] }
function parsePreview(raw: unknown): Preview {
  const data = raw as Preview;
  if (!Array.isArray(data?.clue_stages) || !data.clue_stages.length) throw new Error('文件中没有线索阶段');
  for (const stage of data.clue_stages) {
    if (!Array.isArray(stage.items) || !stage.items.every(item => typeof item.id === 'string' && typeof item.content === 'string')) throw new Error('线索格式不正确');
    const media = [...stage.items.map(item => item.media), stage.presentation?.background];
    for (const item of media) if (item && [item.image_url, item.thumbnail_url].some(url => !/^\/images\/[^?#]+$/.test(url) || url.includes('..'))) throw new Error('图片路径必须指向本地 /images/ 资源');
  }
  return data;
}
export function CluePreview() {
  const [data, setData] = useState<Preview | null>(null);
  const [round, setRound] = useState(0);
  const [active, setActive] = useState<CluePresentationState | null>(null);
  const [error, setError] = useState('');
  const [draft, setDraft] = useState('');
  const [message, setMessage] = useState('');
  const composer = useRef<MentionComposerHandle>(null);
  useEffect(() => {
    const src = new URLSearchParams(location.search).get('src');
    if (!src || !src.startsWith('/images/scripts/') || src.includes('..')) return;
    let cancelled = false;
    fetch(src).then(response => { if (!response.ok) throw new Error('资源文件无法加载'); return response.json(); })
      .then(raw => { if (!cancelled) setData(parsePreview(raw)); }).catch(cause => { if (!cancelled) setError(String(cause)); });
    return () => { cancelled = true; };
  }, []);
  const stage = data?.clue_stages[round];
  const clues = data?.clue_stages.filter(item => item.stage <= (stage?.stage ?? 0)).flatMap(item => item.items) ?? [];
  const send = () => { setMessage(draft); composer.current?.clear(); };
  return <main className="mx-auto max-w-5xl space-y-8 px-5 py-10">
    <header><p className="mb-2 text-xs tracking-[.3em] text-amber-200/60">独醒 · 线索资源工作台</p><h1 className="font-serif text-3xl">{data?.title ?? '线索图片与演出预览'}</h1><p className="mt-3 text-sm text-muted-foreground">本地只读预览。选择资源包中的 preview.json，检查演出、完整线索和发言引用。</p></header>
    <input aria-label="选择预览资源" type="file" accept=".json,application/json" onChange={async event => {
      try { const file = event.target.files?.[0]; if (file) { setData(parsePreview(JSON.parse(await file.text()))); setRound(0); setError(''); } }
      catch (cause) { setError(String(cause)); }
    }} />
    {error && <p role="alert" className="text-red-300">{error}</p>}
    {data && stage && <>
      <nav className="flex flex-wrap gap-3">{data.clue_stages.map((item, index) => <button type="button" key={item.stage} aria-pressed={round === index}
        className="rounded-lg border border-amber-200/30 px-4 py-2 aria-pressed:bg-amber-200/15"
        onClick={() => { setRound(index); setMessage(''); composer.current?.clear(); }}>第 {item.stage} 轮 · {item.presentation?.title ?? '线索'}</button>)}</nav>
      <section className="flex items-center justify-between gap-4 rounded-xl border border-border p-5"><div><h2 className="text-xl">{stage.presentation?.title ?? '本轮线索'}</h2><p className="mt-2 text-sm text-muted-foreground">{stage.items.length} 条线索 · {(stage.presentation?.shots.reduce((sum, shot) => sum + shot.duration_ms, 0) ?? 0) / 1000} 秒</p></div>
        <button className="rounded-lg bg-amber-200 px-5 py-3 text-slate-950" onClick={() => setActive({ presentation_id: 'preview', round: stage.stage, status: 'pending', presentation: stage.presentation ?? null, clues: stage.items, reference_clues: clues })}>播放本轮演出</button></section>
      <section className="rounded-xl border border-border p-5"><h2 className="mb-4 text-lg">发言与引用</h2>
        <MentionComposer ref={composer} characters={[]} clues={clues} onChange={setDraft} onEnter={send} onCtrlEnter={send} />
        <button type="button" className="mt-3 rounded-lg border border-border px-4 py-2" onClick={send}>预览发言</button>
        <p className="my-3 text-xs text-muted-foreground">{draft.length}/3000</p>
        <output className="mb-4 block whitespace-pre-wrap break-all text-xs text-muted-foreground" aria-label="引用序列化文本">{draft}</output>
        {message && <GameMessageMarkdown publicClues={clues} allowedCitationIds={citedIds(message, clues)} preserveWhitespace>{message}</GameMessageMarkdown>}
      </section>
      <section className="rounded-xl border border-border p-5"><h2 className="mb-4 text-lg">本轮完整线索</h2><ClueDetails clues={stage.items} /></section>
    </>}
    {active && <CluePresentationOverlay state={active} onContinue={async () => setActive(null)} />}
  </main>;
}
createRoot(document.getElementById('root')!).render(<StrictMode><CluePreview /></StrictMode>);
