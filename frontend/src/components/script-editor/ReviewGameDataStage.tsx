import { useEffect, useRef, useState } from 'react';
import * as Tooltip from '@radix-ui/react-tooltip';
import { ArrowDown, ArrowUp, BookOpen, Check, FileSearch, Flag, Plus, Trash2, Users, Layers, Megaphone } from 'lucide-react';
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Markdown } from '@/components/ui/Markdown';
import { useEditorStore } from '@/stores/editorStore';
import { STEP_VOICE_GROUPS } from '@/lib/stepVoices';
import type { CharacterGameData, EditorInterruptInfo, EditorWorkflowState, GameDataSections, QualityTarget } from '@/types/editor';
import { WorkshopField } from './WorkshopField';
import { EndingEditor } from './EndingEditor';
import { RefineButton } from './RefineButton';
import { useTextDraft } from './useTextDraft';
import { submissionData } from './gameDataAdapter';
import { normalizeQualityReport } from './qualityReport';

const chapters = [
  { id: 'public', label: '公开介绍', note: '让玩家走进故事', icon: BookOpen },
  { id: 'characters', label: '角色', note: '每个人眼中的真相', icon: Users },
  { id: 'clues', label: '分轮线索', note: '安排信息揭示的节奏', icon: Layers },
  { id: 'host', label: '主持流程', note: '从开场到最终投票', icon: Megaphone },
  { id: 'truth', label: '真相与结局', note: '故事的完整答案', icon: Flag },
];
const control = 'rounded-lg border border-border bg-background px-3 py-2 text-sm focus:outline-primary';

export function ReviewGameDataStage({ editedGameData: draft, setEditedGameData, isLoading, currentStep,
  onConfirmGameData, interruptInfo, error, scriptTitle, workflowState }: {
  editedGameData: GameDataSections | null; setEditedGameData: (value: GameDataSections | null) => void;
  isLoading: boolean; currentStep: string; onConfirmGameData: (value: GameDataSections) => Promise<void>;
  interruptInfo: EditorInterruptInfo; error: string | null; scriptTitle: string;
  workflowState: EditorWorkflowState | null;
}) {
  const [view, setView] = useTextDraft('game-data-navigation', '', { section: 'public', role: '', round: 1, reportOpen: false });
  const [preview, setPreview] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [voices, setVoices] = useState(STEP_VOICE_GROUPS.flatMap(group => group.voices));
  const scroller = useRef<HTMLDivElement>(null);
  const positions = useRef<Record<string, number>>({});
  const [target, setTarget] = useState<QualityTarget | null>(null);
  const resume = useEditorStore(s => s.resumeWorkflow);
  const report = normalizeQualityReport(workflowState?.quality_report) || normalizeQualityReport(interruptInfo.quality_report);
  const reportChanged = Boolean(report?.source_sections && draft && JSON.stringify(submissionData(draft)) !== JSON.stringify(report.source_sections));
  useEffect(() => {
    const controller = new AbortController();
    void fetch('/api/v1/system/voices', { signal: controller.signal }).then(r => r.ok ? r.json() : null)
      .then(result => { if (result?.voices?.length) setVoices(result.voices); }).catch(() => {});
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!target || view.reportOpen) return;
    const frame = requestAnimationFrame(() => {
      const key = [target.section, target.entity_id || '', target.field].join(':');
      scroller.current?.querySelectorAll('.ring-2.ring-primary').forEach(el => el.classList.remove('ring-2', 'ring-primary'));
      const element = Array.from(scroller.current?.querySelectorAll<HTMLElement>('[data-field-target]') || []).find(el => el.dataset.fieldTarget === key);
      if (element) {
        element.scrollIntoView({ block: 'center', behavior: 'auto' });
        (element.querySelector<HTMLElement>('textarea, input') || element.querySelector<HTMLElement>('button'))?.focus({ preventScroll: true });
        element.classList.add('ring-2', 'ring-primary');
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [target, view.reportOpen, view.role, view.round, view.section]);
  if (!draft) return <p className="p-6 text-muted-foreground">正在准备游戏数据…</p>;
  const data = draft;
  const roles = data.character_data || [];
  const role = roles.find(item => item.character_id === view.role) || roles[0];
  const round = data.clue_stages.find(item => item.stage === view.round) || data.clue_stages[0];
  const change = (recipe: (next: GameDataSections) => void) => {
    const next = submissionData(data); recipe(next); setEditedGameData(submissionData(next));
  };
  const field = (key: keyof GameDataSections, value: unknown) => change(next => { Object.assign(next, { [key]: value }); });
  const changeRole = (key: keyof CharacterGameData, value: unknown) => change(next => {
    const item = next.character_data.find(item => item.character_id === role.character_id);
    if (item) Object.assign(item, { [key]: value });
  });
  const switchSection = (section: string) => {
    positions.current[view.section] = scroller.current?.scrollTop || 0;
    setView({ ...view, section });
    requestAnimationFrame(() => { if (scroller.current) scroller.current.scrollTop = positions.current[section] || 0; });
  };
  const jump = (location: QualityTarget) => {
    setTarget(location); setAdvanced(location.field === 'system_prompt');
    setView({ ...view, reportOpen: false, section: location.section,
      role: location.section === 'characters' ? location.entity_id || '' : view.role,
      round: location.stage || view.round });
  };
  const check = async () => {
    setTarget(null);
    setView({ ...view, reportOpen: true });
    if (!report && !workflowState?.quality_check_attempted) await resume('quality_check', undefined, undefined, submissionData(data));
  };
  const sceneText = (type: string, index: number) => String((data.game_flow.find(s => s.type === type)?.children as Array<Record<string, unknown>> | undefined)?.[index]?.system_notice || '');
  const changeScene = (type: string, index: number, value: string) => change(next => {
    const children = next.game_flow.find(s => s.type === type)?.children as Array<Record<string, unknown>> | undefined;
    if (children?.[index]) children[index].system_notice = value;
  });
  const section = chapters.find(item => item.id === view.section) || chapters[0];
  return <Tooltip.Provider delayDuration={200}><div className="flex h-full min-h-0 flex-col" data-testid="game-data-workspace">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border/50 px-5 py-4">
      <div><h2 className="font-semibold">让故事成为可以游玩的剧本</h2><p className="mt-1 text-xs text-muted-foreground">按玩家看到故事的方式，检查并完善每一部分。</p></div>
      <span className="flex items-center gap-1.5 text-xs text-muted-foreground"><Check className="size-3.5" />下一步会提交全部当前修改</span>
    </header>
    {error && <p role="alert" className="border-b border-destructive/30 bg-destructive/5 px-5 py-3 text-sm text-destructive">{error}</p>}
    {interruptInfo.rejected && <p role="alert" className="bg-destructive/5 px-5 py-3 text-sm text-destructive">{interruptInfo.reason}</p>}
    {Boolean(interruptInfo.validation_errors?.length) && <ul role="alert" className="list-disc bg-destructive/5 px-9 py-3 text-sm text-destructive">{interruptInfo.validation_errors?.map(message => <li key={message}>{message}</li>)}</ul>}
    <fieldset disabled={isLoading} className="flex min-h-0 flex-1 flex-col md:flex-row disabled:opacity-70">
      <nav aria-label="游戏数据章节" className="hidden w-48 shrink-0 space-y-1 border-r border-border/50 bg-secondary/10 p-3 md:block">
        {chapters.map(item => <button key={item.id} type="button" onClick={() => switchSection(item.id)} aria-current={view.section === item.id ? 'page' : undefined}
          className={`flex w-full items-start gap-3 rounded-xl px-3 py-3 text-left ${view.section === item.id ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-secondary/60'}`}>
          <item.icon className="mt-0.5 size-4 shrink-0" /><span><span className="block text-sm font-medium">{item.label}</span><span className="mt-1 block text-[11px] opacity-70">{item.note}</span></span>
        </button>)}
      </nav>
      <label className="border-b border-border p-3 text-xs md:hidden">编辑章节
        <select aria-label="编辑章节" value={view.section} onChange={e => switchSection(e.target.value)} className={`${control} ml-3`}>
          {chapters.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>
      </label>
      <div ref={scroller} className="min-h-0 min-w-0 flex-1 overflow-y-auto p-4 sm:p-6">
        <div className="mx-auto max-w-4xl space-y-5">
          <div className="mb-6"><p className="text-xs tracking-widest text-primary">{String(chapters.indexOf(section) + 1).padStart(2, '0')} / 05</p><h3 className="mt-2 text-xl font-semibold">{section.label}</h3><p className="mt-1 text-sm text-muted-foreground">{section.note}</p></div>
          {view.section === 'public' && <>
            <div className="grid gap-4 sm:grid-cols-[2fr_1fr]">
              <WorkshopField label="剧本名称" value={data.title ?? scriptTitle} onChange={value => field('title', value)} compact target="public::title" />
              <label className="rounded-xl border border-border/50 p-4 text-sm">难度<select aria-label="剧本难度" className={`${control} mt-3 w-full`} value={data.difficulty ?? workflowState?.difficulty ?? 1} onChange={e => field('difficulty', Number(e.target.value))}>{['简单', '中等', '困难', '极难'].map((label, i) => <option key={label} value={i + 1}>{label}</option>)}</select></label>
            </div>
            <WorkshopField label="标签" compact value={data.tags} onChange={value => field('tags', value)} help="用逗号分隔，帮助玩家了解题材与风格。" />
            <WorkshopField label="大厅简介" value={data.overview} onChange={value => field('overview', value)} audience="所有玩家可见" help="出现在剧本大厅，介绍故事前提并保留悬念。" target="public::overview" />
            <WorkshopField label="详情介绍" value={data.description} onChange={value => field('description', value)} audience="所有玩家可见" target="public::description" />
            <button onClick={() => setPreview(!preview)} className="text-sm text-primary">{preview ? '收起公开预览' : '查看公开预览'}</button>
            {preview && <article className="rounded-xl border border-primary/30 bg-primary/5 p-6"><p className="text-xs text-muted-foreground">玩家视角 · 公开内容</p><h3 className="my-3 text-2xl font-semibold">{data.title || scriptTitle}</h3><p className="mb-4 text-sm">{data.overview}</p><Markdown>{data.description || ''}</Markdown></article>}
          </>}
          {view.section === 'characters' && role && <>
            <div className="flex flex-wrap gap-2" role="group" aria-label="选择编辑角色">{roles.map(item => <button key={item.character_id} onClick={() => setView({ ...view, role: item.character_id })} aria-pressed={role.character_id === item.character_id}
              className={`rounded-full border px-4 py-2 text-sm ${role.character_id === item.character_id ? 'border-primary bg-primary/10 text-primary' : 'border-border'}`}>{item.name}</button>)}</div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {(['name', 'gender', 'age', 'occupation'] as const).map((key, index) => <label key={key} className="text-xs text-muted-foreground">{['姓名', '性别', '年龄', '公开身份'][index]}<input aria-label={['角色姓名', '角色性别', '角色年龄', '角色身份'][index]} type={key === 'age' ? 'number' : 'text'} value={role[key] ?? ''} onChange={e => changeRole(key, key === 'age' ? Number(e.target.value) : e.target.value)} className={`${control} mt-2 w-full`} /></label>)}
            </div>
            <WorkshopField key={`${role.character_id}:script`} label="个人剧本" value={role.character_script ?? data.character_scripts[role.name]} onChange={value => changeRole('character_script', value)} audience="仅本人可见" help="保留本人经历与实际行为，不提前写入其他角色的秘密或后续公布的鉴定。" target={`characters:${role.character_id}:character_script`} />
            <WorkshopField key={`${role.character_id}:summary`} label="角色速览" value={role.script_summary} onChange={value => changeRole('script_summary', value)} audience="仅本人可见" help="选定角色后，仅对应玩家可见。应忠实提炼个人剧本。" target={`characters:${role.character_id}:character_script_summary`} />
            <WorkshopField label="公开简介" value={role.profile} onChange={value => changeRole('profile', value)} audience="所有玩家可见" help="将在选择角色时向玩家展示" target={`characters:${role.character_id}:profile`} />
            <h4 className="pt-3 text-sm font-semibold">形象与声音</h4>
            <WorkshopField label="外貌描述" value={role.appearance} onChange={value => changeRole('appearance', value)} help="将用于角色形象生成" />
            <label className="block text-sm">角色声音<select aria-label="角色声音" value={role.step_voice_id || ''} onChange={e => changeRole('step_voice_id', e.target.value)} className={`${control} mt-2 w-full`}><option value="">自动选择</option>{voices.map(voice => <option key={voice.id} value={voice.id}>{voice.label}</option>)}</select></label>
            <button aria-expanded={advanced} onClick={() => setAdvanced(!advanced)} className="text-sm text-muted-foreground">{advanced ? '收起高级设置' : '高级设置 · AI 扮演资料'}</button>
            {advanced && <WorkshopField label="AI 扮演资料" value={role.system_prompt} onChange={value => changeRole('system_prompt', value)} audience="仅对应 AI 角色使用" help="与个人剧本保持一致，不能给 AI 额外的全知信息。" target={`characters:${role.character_id}:system_prompt`} />}
          </>}
          {view.section === 'clues' && round && <>
            <div className="flex flex-wrap gap-2" role="group" aria-label="线索轮次">{data.clue_stages.map(item => <button key={item.stage} aria-pressed={round.stage === item.stage} onClick={() => setView({ ...view, round: item.stage })} className={`${control} ${round.stage === item.stage ? 'border-primary text-primary' : ''}`}>第 {item.stage} 轮 · {item.items.length} 条线索</button>)}</div>
            <WorkshopField label="本轮概述" value={round.overview} onChange={value => change(next => { next.clue_stages.find(s => s.stage === round.stage)!.overview = value; })} audience={`第 ${round.stage} 轮公布`} target={`clues:${round.stage}:overview`} />
            {round.items.map((clue, index) => <article key={clue.id || index} className="space-y-3 rounded-2xl border border-border bg-secondary/10 p-4">
              <div className="flex items-center justify-between"><span className="text-xs text-muted-foreground">线索 {index + 1} · 第 {round.stage} 轮公布</span><div className="flex gap-3">
                {[-1, 1].map(offset => <button key={offset} aria-label={`${offset < 0 ? '上移' : '下移'}线索${index + 1}`} disabled={index + offset < 0 || index + offset >= round.items.length} onClick={() => change(next => { const items = next.clue_stages.find(s => s.stage === round.stage)!.items; [items[index], items[index + offset]] = [items[index + offset], items[index]]; })} className="disabled:opacity-20">{offset < 0 ? <ArrowUp className="size-4" /> : <ArrowDown className="size-4" />}</button>)}
                <button aria-label={`删除线索${index + 1}`} disabled={round.items.length <= 1} onClick={() => change(next => { const stage = next.clue_stages.find(s => s.stage === round.stage)!; stage.items = stage.items.filter((_, i) => i !== index); })}><Trash2 className="size-4 text-muted-foreground" /></button>
              </div></div>
              <WorkshopField label={`线索 ${index + 1} 标题`} compact value={clue.summary} onChange={value => change(next => { next.clue_stages.find(s => s.stage === round.stage)!.items[index].summary = value; })} target={`clues:${clue.id}:summary`} />
              <WorkshopField label={`线索 ${index + 1} 正文`} value={clue.content} onChange={value => change(next => { next.clue_stages.find(s => s.stage === round.stage)!.items[index].content = value; })} target={`clues:${clue.id}:content`} />
            </article>)}
            <button onClick={() => change(next => { next.clue_stages.find(s => s.stage === round.stage)!.items.push({ id: `clue-${crypto.randomUUID().replaceAll('-', '').slice(0, 12)}`, stage: round.stage, summary: '', content: '' }); })} className="inline-flex items-center gap-2 text-sm text-primary"><Plus className="size-4" />添加本轮线索</button>
            <WorkshopField label="讨论提示" value={round.free_discussion_notice} onChange={value => change(next => { next.clue_stages.find(s => s.stage === round.stage)!.free_discussion_notice = value; })} help="一句自然的讨论邀请即可，给玩家保留推理与表达空间。" target={`clues:${round.stage}:free_discussion_notice`} />
            <label className="block text-sm">每位角色本轮发言次数<select aria-label="本轮发言次数" className={`${control} ml-3`} value={data.free_speech_limits[data.clue_stages.indexOf(round)] || 2} onChange={e => change(next => { next.free_speech_limits[next.clue_stages.findIndex(s => s.stage === round.stage)] = Number(e.target.value); })}>{[1, 2, 3].map(n => <option key={n} value={n}>{n} 次</option>)}</select></label>
          </>}
          {view.section === 'host' && <>
            <WorkshopField label="开场叙述" value={data.opening} onChange={value => field('opening', value)} audience="开局公开" target="host::game_full_process[0].system_notice" />
            <div className="rounded-lg bg-secondary/30 p-4 text-sm text-muted-foreground">随后依次公布 {data.clue_stages.length} 轮线索并讨论，可在“分轮线索”中编辑。</div>
            <WorkshopField label="总结发言提示" value={sceneText('vote', 0)} onChange={value => changeScene('vote', 0, value)} audience="所有线索公布后" target={`host::game_full_process[${data.game_flow.findIndex(s => s.type === 'vote')}].children[0].system_notice`} />
            <WorkshopField label="投票提示" value={sceneText('vote', 1)} onChange={value => changeScene('vote', 1, value)} audience="最终投票时" target={`host::game_full_process[${data.game_flow.findIndex(s => s.type === 'vote')}].children[1].system_notice`} />
          </>}
          {view.section === 'truth' && <>
            <WorkshopField label="完整真相" value={data.full_truth} onChange={value => field('full_truth', value)} audience="结局公布" target="truth::full_truth" />
            <WorkshopField label="揭晓文案" value={data.truth_reveal} onChange={value => field('truth_reveal', value)} audience="结局公布" />
            <EndingEditor data={data} onChange={value => field('ending_config', value)} />
          </>}
        </div>
      </div>
    </fieldset>
    <footer className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-border/50 bg-background px-4 py-3">
      <button disabled={isLoading} onClick={() => void check()} className="inline-flex items-center gap-2 rounded-lg border border-border px-4 py-2.5 text-sm disabled:opacity-40"><FileSearch className="size-4" />{report || workflowState?.quality_check_attempted ? '质检报告' : '质量检查（可选）'}</button>
      <div className="grid grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] gap-2"><RefineButton step="review_game_data" gameData={submissionData(data)} disabled={isLoading} />
        <button disabled={isLoading} onClick={() => void onConfirmGameData(submissionData(data))} className="rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground disabled:opacity-40">{isLoading ? currentStep === 'check_game_quality' ? '正在检查…' : '正在进行合规评估…' : '下一步 · 生成资源'}</button>
      </div>
    </footer>
    <Dialog open={view.reportOpen && !isLoading} onOpenChange={value => setView({ ...view, reportOpen: value })}><DialogContent className="sm:max-w-2xl" onCloseAutoFocus={event => { if (target) event.preventDefault(); }}>
      <DialogTitle>游戏数据质检报告</DialogTitle><DialogDescription>供创作参考；无论是否修改，均可继续下一步。本流程仅检查一次。</DialogDescription>
      {reportChanged && <p role="status" className="rounded-lg bg-amber-500/10 p-3 text-sm">检查后内容已有变化。这是检查时版本的报告，不代表当前草稿。</p>}
      {!report || report.status === 'incomplete' ? <p className="text-sm text-muted-foreground">{report?.error || '本次检查未完成，仍可继续创作。'}</p> : report.findings.length === 0 ? <p className="rounded-lg bg-primary/5 p-4 text-sm">本次未发现可证实的关键错误。</p> :
        report.findings.map((finding, i) => <article key={i} className="space-y-3 rounded-xl border border-border p-4">
          <p className="text-sm font-medium">{finding.impact}</p><blockquote className="border-l-2 border-primary/40 pl-3 text-sm text-muted-foreground">{finding.evidence}</blockquote>
          <p className="text-sm leading-relaxed">建议：{finding.suggestion}</p>
          {finding.target && <button onClick={() => jump(finding.target!)} className="text-left text-sm text-primary">定位：{finding.target.label} →</button>}
        </article>)}
    </DialogContent></Dialog>
  </div></Tooltip.Provider>;
}
