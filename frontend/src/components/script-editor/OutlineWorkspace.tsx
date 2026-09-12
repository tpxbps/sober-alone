import { useEffect, useRef, useState } from "react";
import { ArrowDown, Check, History, Loader2, RotateCcw, Sparkles } from "lucide-react";
import { Markdown } from "@/components/ui/Markdown";
import { useEditorStore } from "@/stores/editorStore";
import type { OutlineQuestion, OutlineSession } from "@/types/outline";
import { useOutlineSession } from "./useOutlineSession";

const statusLabels: Record<string, string> = {
  writing: "正在撰写", directing: "正在评估大纲后续发展…",
  awaiting_answer: "等待你的选择", finalizing: "正在整理完整大纲",
  checking: "正在完成大纲", ready: "大纲已整理，等待你确认",
  needs_revision: "大纲已整理，等待你确认",
};
type Draft = { option?: string; text: string };
const emptyDraft: Draft = { text: "" };

function QuestionCard({ question, draft, onChange, onSubmit, disabled, rewrite = false }: {
  question: OutlineQuestion; draft: Draft; onChange: (value: Draft) => void;
  onSubmit: () => void; disabled: boolean; rewrite?: boolean;
}) {
  return <section data-outline-question className="rounded-2xl border border-primary/30 bg-primary/5 p-5 space-y-4" aria-label={question.title}>
    <div><p className="text-sm font-medium text-primary">{question.title}</p>
      <h3 className="mt-2 text-lg font-semibold leading-relaxed">{question.question}</h3></div>
    <div className="grid gap-2" role="radiogroup" aria-label="剧情方向">
      {question.options.map(option => <button type="button" role="radio" aria-checked={draft.option === option.id}
        key={option.id} disabled={disabled} onClick={() => onChange({ ...draft, option: draft.option === option.id ? undefined : option.id })}
        className={`rounded-xl border p-3 text-left transition-colors ${draft.option === option.id ? "border-primary bg-primary/10" : "border-border/60 bg-background/50 hover:border-primary/50"} disabled:opacity-50`}>
        <span className="flex items-center gap-2 font-medium text-sm">{option.label}
          {question.recommended_option_id === option.id && <span className="rounded bg-primary/15 px-1.5 py-0.5 text-[11px] text-primary">推荐</span>}
        </span><span className="mt-1 block text-sm leading-relaxed text-muted-foreground">{option.impact}</span>
      </button>)}
    </div>
    <label className="block text-sm space-y-2"><span>其他想法或补充说明</span>
      <textarea value={draft.text} maxLength={8000} disabled={disabled}
        onChange={e => onChange({ ...draft, text: e.target.value })}
        placeholder="可以直接写下其他方向，也可以补充所选方向的细节…" rows={3}
        className="w-full resize-y rounded-xl border border-border bg-background p-3 outline-none focus:border-primary" />
    </label>
    <button disabled={disabled || (!draft.option && !draft.text.trim())} onClick={onSubmit}
      className="rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground disabled:opacity-40">
      {rewrite ? "从这里重写后续" : "按此方向继续"}
    </button>
  </section>;
}

export function OutlineWorkspace({ threadId }: { threadId: string | null }) {
  const { progress, error, busy, act } = useOutlineSession(threadId);
  const workflow = useEditorStore(s => s.workflowState);
  const storeError = useEditorStore(s => s.error);
  const currentStep = useEditorStore(s => s.currentStep);
  const resume = useEditorStore(s => s.resumeWorkflow);
  const fetchHistory = useEditorStore(s => s.fetchHistory);
  const history = useEditorStore(s => s.history);
  const [tab, setTab] = useState<"chat" | "outline">("chat");
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [rewriting, setRewriting] = useState<OutlineQuestion | null>(null);
  const [viewVersion, setViewVersion] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const [editedOutline, setEditedOutline] = useState("");
  const [hasNew, setHasNew] = useState(false);
  const scroll = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const shownQuestion = useRef<string | null>(null);
  const session = progress?.session || workflow?.outline_session;
  const archived = viewVersion === null ? null : history.find(cp => cp.state.outline_session?.revision === viewVersion)?.state;
  const visible: OutlineSession | null | undefined = archived?.outline_session || session;
  const paused = Boolean(progress?.control.paused);
  const stopped = Boolean(progress?.control.questions_stopped || session?.questions_stopped);
  const final = currentStep === "review_outline" && ["ready", "needs_revision"].includes(session?.status || "");
  const live = archived ? null : progress?.live;
  const finalText = live?.segment_id === "final" ? live.text : visible?.final_outline;
  const hasFinalMessage = live?.segment_id === "final" || Boolean(visible?.final_outline);
  const waiting = !archived && !paused && !final && !live && !session?.pending_question && !rewriting;
  const workflowBusy = useEditorStore(s => s.isLoading);
  const disabled = busy || workflowBusy;
  const text = visible?.final_outline || (archived ? archived.outline : workflow?.outline) || visible?.segments.map(s => s.content).join("\n\n") || "";
  const activeError = error || progress?.error || storeError || "";
  const pending = session?.pending_question;
  const activeQuestion = rewriting || pending;
  const activeQuestionId = activeQuestion?.id;
  const draftKey = `${session?.revision}:${activeQuestion?.id || ""}:${rewriting ? "rewrite" : "answer"}`;
  const draft = drafts[draftKey] || emptyDraft;

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      if (!scroll.current) return;
      if (following.current) {
        const card = scroll.current.querySelector<HTMLElement>("[data-outline-question]");
        if (card && activeQuestionId) {
          if (shownQuestion.current !== draftKey) {
            scroll.current.scrollTop += card.getBoundingClientRect().top - scroll.current.getBoundingClientRect().top - 16;
            shownQuestion.current = draftKey;
          }
        } else {
          shownQuestion.current = null;
          scroll.current.scrollTop = scroll.current.scrollHeight;
        }
      } else setHasNew(true);
    });
    return () => cancelAnimationFrame(frame);
  }, [progress?.seq, activeQuestionId, draftKey]);

  useEffect(() => { if (threadId) void fetchHistory(); }, [threadId, session?.revision, final, fetchHistory]);

  const startRewrite = (question: OutlineQuestion) => {
    setViewVersion(null);
    setTab("chat");
    setRewriting(question);
    following.current = true;
  };
  const submit = async () => {
    if (!activeQuestion) return;
    if (await act({ action: rewriting ? "rewrite" : "answer", question_id: activeQuestion.id,
      option_id: draft.option, other_text: draft.text })) {
      setRewriting(null);
      setDrafts(old => ({ ...old, [draftKey]: emptyDraft }));
    }
  };
  const versions = [...new Set(history.map(cp => cp.state.outline_session?.revision).filter((v): v is number => Boolean(v)))];
  return <div className="flex h-full min-h-0 flex-col" data-testid="outline-workspace">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/40 px-4 py-3">
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-primary" /><h2 className="font-semibold">一起创作大纲</h2>
        <span className="text-xs text-muted-foreground">版本 {viewVersion || session?.revision || 1}</span>
      </div>
      <div className="flex items-center gap-2">
        {versions.length > 1 && <label className="flex items-center gap-1 text-xs text-muted-foreground"><History className="h-3.5 w-3.5" />
          <select aria-label="查看大纲版本" value={viewVersion ?? ""} onChange={e => setViewVersion(e.target.value ? Number(e.target.value) : null)}
            className="rounded border border-border bg-background p-1.5"><option value="">当前版本</option>
            {versions.filter(v => v !== session?.revision).map(v => <option key={v} value={v}>版本 {v}（只读）</option>)}</select>
        </label>}
        {(["chat", "outline"] as const).map(value => <button key={value} onClick={() => setTab(value)}
          aria-pressed={tab === value} className={`rounded-lg px-3 py-1.5 text-sm ${tab === value ? "bg-secondary text-foreground" : "text-muted-foreground"}`}>
          {value === "chat" ? "共创对话" : "当前大纲"}</button>)}
      </div>
    </div>
    <div className="relative min-h-0 flex-1">
      <div ref={scroll} onScroll={() => { const el = scroll.current; if (el) {
        following.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        if (following.current) setHasNew(false);
      }}} className="h-full overflow-y-auto px-4 py-6 scrollbar-thin">
        <div className="mx-auto max-w-[860px] space-y-5 pb-4">
          {archived && <p className="rounded-lg bg-secondary/50 p-3 text-sm">正在查看旧版本；内容不会加入当前创作。</p>}
          {tab === "chat" ? <>
            <div className="ml-auto max-w-[90%] rounded-2xl rounded-tr-sm bg-secondary/60 p-4 text-sm whitespace-pre-wrap">{workflow?.user_idea || "从你的创意出发，先写下一小段开篇…"}</div>
            {visible?.segments.map((segment, index) => <div key={segment.id} className="space-y-4">
              <article className="rounded-2xl rounded-tl-sm border border-border/50 bg-card/40 px-5 py-4"><Markdown>{segment.content}</Markdown></article>
              {visible.decisions.filter(d => (d.segment_index ?? index + 1) === index + 1).map((decision, di) => <div key={di} className="ml-auto max-w-[92%] rounded-xl bg-secondary/40 p-4 text-sm">
                {decision.question && <p className="mb-2 font-medium">{decision.question.question}</p>}
                {decision.source === "user" && <p className="mb-1 text-xs text-muted-foreground">你的决定</p>}
                <p>{decision.choice}</p>{decision.other_text && <p className="mt-1 whitespace-pre-wrap">{decision.other_text}</p>}
                {!archived && decision.question && <button disabled={disabled} onClick={() => void startRewrite(decision.question!)}
                  className="mt-3 inline-flex items-center gap-1 text-xs text-primary"><RotateCcw className="h-3 w-3" />从这里修改</button>}
              </div>)}
            </div>)}
            {live && live.segment_id !== "final" && <article className="rounded-2xl border border-primary/20 bg-card/40 px-5 py-4" aria-label="正在撰写">
              <p className="mb-3 flex items-center gap-2 text-xs text-primary"><Loader2 className={`h-3 w-3 ${paused ? "" : "animate-spin"}`} />
                {paused ? "未完成草稿 · 恢复后重写这一段" : "正在撰写"}</p>
              <Markdown>{live.text || "…"}</Markdown>
            </article>}
            {hasFinalMessage && <article key={`final-${visible?.revision}`} data-testid="outline-final-message"
              className="rounded-2xl border border-primary/20 bg-card/40 px-5 py-4" aria-label="完整大纲">
              <p className="mb-3 flex items-center gap-2 text-xs text-primary">
                {live?.segment_id === "final" && <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" />}
                {live?.segment_id === "final" ? "正在整理完整大纲" : "完整大纲"}</p>
              <Markdown>{finalText || "…"}</Markdown>
            </article>}
            {waiting && !activeError && <div role="status" data-testid="outline-writing-status"
              className="flex items-center gap-3 rounded-2xl border border-border/40 bg-card/40 px-5 py-4 text-sm text-muted-foreground">
              <span aria-hidden="true" className="flex gap-1">{[0, 1, 2].map(i => <span key={i}
                className="h-1.5 w-1.5 rounded-full bg-primary/70 animate-pulse motion-reduce:animate-none" style={{ animationDelay: `${i * 180}ms` }} />)}</span>
              {session?.status === "directing" ? "正在评估大纲后续发展…" : session?.status === "finalizing" ? "正在整理完整大纲…" : session?.segments.length ? "正在继续撰写…" : "正在撰写开篇…"}
            </div>}
            {!archived && paused && !final && <div className="rounded-xl border border-border p-4 text-sm">
              上次创作尚未完成。<button disabled={disabled} onClick={() => void act({ action: "continue" })} className="ml-2 text-primary">恢复大纲创作</button>
            </div>}
            {!archived && rewriting && <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm">
              修改此处后，该回答及之后的内容会重写，旧版本仍可查看。
              <button className="ml-3 text-primary" onClick={() => setRewriting(null)}>取消修改</button>
            </div>}
            {!archived && activeQuestion && !stopped && <QuestionCard question={activeQuestion} draft={draft}
              onChange={value => setDrafts(old => ({ ...old, [draftKey]: value }))}
              onSubmit={() => void submit()} disabled={disabled || (paused && !rewriting)} rewrite={Boolean(rewriting)} />}
            {!archived && rewriting && stopped && <QuestionCard question={rewriting} draft={draft}
              onChange={value => setDrafts(old => ({ ...old, [draftKey]: value }))}
              onSubmit={() => void submit()} disabled={disabled} rewrite />}
            {!archived && final && <div className="rounded-xl border border-primary/25 p-4 text-sm">
              <p className="font-medium">完整大纲已整理</p><p className="mt-1 text-muted-foreground">查看全文、修改内容，再决定是否进入初稿。</p>
              <button onClick={() => setTab("outline")} className="mt-3 text-primary">查看完整大纲 →</button>
            </div>}
          </> : editing && !archived ? <textarea aria-label="编辑完整大纲" value={editedOutline} onChange={e => setEditedOutline(e.target.value)}
            className="min-h-[55vh] w-full rounded-xl border border-border bg-background p-4 text-sm leading-7 outline-none focus:border-primary" />
            : <article className="rounded-xl border border-border/40 p-5"><Markdown>{live?.segment_id === "final" ? live.text : text || "正文将随创作逐段出现在这里。"}</Markdown>
              {live && live.segment_id !== "final" && <div className="mt-6 border-t border-border/40 pt-4"><p className="mb-2 text-xs text-primary">正在撰写</p><Markdown>{live.text}</Markdown></div>}
            </article>}
          {!archived && activeError && <div role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm">
            <p>{activeError}</p><button disabled={disabled} onClick={() => void act({ action: "retry" })} className="mt-2 text-primary">重试当前步骤</button>
          </div>}
        </div>
      </div>
      {hasNew && <button onClick={() => { following.current = true; setHasNew(false); scroll.current?.scrollTo({ top: scroll.current.scrollHeight, behavior: "smooth" }); }}
        className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1 rounded-full border border-border bg-background px-4 py-2 text-xs shadow-lg"><ArrowDown className="h-3 w-3" />回到最新</button>}
    </div>
    {!archived && <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-border/40 px-4 py-3">
      <span className="text-xs text-muted-foreground" role="status">{disabled ? "正在处理…" : paused ? "创作已暂停" : statusLabels[session?.status || "writing"]}{stopped && !final ? " · AI将自动完成后续大纲创作" : ""}</span>
      <div className="flex flex-wrap items-center gap-2">
        {final ? <>
          <button disabled={disabled} onClick={() => { if (!editing) { setEditedOutline(text); setTab("outline"); } setEditing(!editing); }}
            className="rounded-lg border border-border px-3 py-2 text-sm">{editing ? "取消编辑" : "编辑全文"}</button>
          <button disabled={disabled || (editing && !editedOutline.trim())} onClick={() => void resume("confirm", editing ? editedOutline : text)}
            className="inline-flex items-center gap-1 rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground"><Check className="h-4 w-4" />确认大纲，进入初稿</button>
        </> : <>
          {!stopped && <div className="flex flex-wrap items-center gap-2">
            <button disabled={disabled || !threadId} onClick={() => void act({ action: "stop_questions" })}
              className="rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-40">停止提问</button>
            <span className="text-xs text-muted-foreground">AI将自动完成后续大纲创作</span>
          </div>}
        </>}
      </div>
    </footer>}
  </div>;
}
