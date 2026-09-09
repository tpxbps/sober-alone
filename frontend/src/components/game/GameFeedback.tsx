import { useEffect, useState } from "react";
import { ThumbsUp, ThumbsDown } from "lucide-react";
import api from "@/lib/api";
import { useGameStore } from "@/stores/gameStore";

type Feedback = { recommended: boolean; comment: string; updated_at: string };

export function GameFeedback() {
  const sessionId = useGameStore((state) => state.sessionId);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [comment, setComment] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  useEffect(() => {
    let active = true;
    if (!sessionId) return;
    api.get(`/game/${sessionId}/feedback`).then(({ data }) => {
      if (!active) return;
      setFeedback(data.feedback); setComment(data.feedback?.comment || ""); setReady(true);
    }).catch((failure) => {
      if (!active) return;
      const status = failure.response?.status;
      if (status === 403 || status === 409) setMessage("该对局暂不具备评价资格。新建对局完成投票并揭晓真相后可评价。");
      else { setReady(true); setError("暂时无法读取评价，可以重新提交。"); }
    });
    return () => { active = false; };
  }, [sessionId]);
  const submit = async (recommended: boolean, includeComment = false) => {
    if (!sessionId || busy) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const { data } = await api.put(`/game/${sessionId}/feedback`, {
        recommended, ...(includeComment ? { comment } : {}),
      });
      setFeedback(data.feedback); setMessage(includeComment ? "体验意见已保存，谢谢你的反馈。" : "评价已保存，谢谢你的反馈。");
    } catch { setError("提交失败，输入已保留，请重试。"); }
    finally { setBusy(false); }
  };
  return <section aria-label="剧本体验评价" className="max-w-3xl mx-auto border border-border/60 bg-card/50 rounded-xl p-4 space-y-3">
    <div><h3 className="text-sm font-medium">这个剧本值得推荐吗？</h3><p className="text-xs text-muted-foreground mt-1">你的反馈会帮助后来玩家选择剧本。</p></div>
    <div className="flex flex-wrap gap-2">
      {[true, false].map((recommended) => { const Icon = recommended ? ThumbsUp : ThumbsDown; return <button key={String(recommended)}
        aria-pressed={feedback?.recommended === recommended} disabled={!ready || busy} onClick={() => submit(recommended)}
        className={`flex items-center gap-2 px-4 py-2 rounded-lg border text-sm disabled:opacity-50 ${feedback?.recommended === recommended ? "border-primary bg-primary/15 text-primary" : "border-border hover:bg-secondary"}`}>
        <Icon size={15} />{recommended ? "推荐" : "不推荐"}</button>; })}
      <button disabled={!ready} aria-expanded={expanded} onClick={() => setExpanded(!expanded)} className="text-xs text-muted-foreground hover:text-primary px-2">{expanded ? "收起体验意见" : "留下体验意见（可选）"}</button>
    </div>
    {expanded && <div className="space-y-2">
      <textarea aria-label="剧本体验意见" value={comment} onChange={(e) => setComment(e.target.value)} maxLength={1000} disabled={busy}
        placeholder="留下你的体验感受或意见…" className="w-full min-h-24 rounded-lg bg-background/60 border border-border p-3 text-sm" />
      <div className="flex justify-between gap-3 text-xs text-muted-foreground"><span>文字仅供维护者查看，不公开展示。</span><span>{comment.length}/1000</span></div>
      <button disabled={!feedback || busy} onClick={() => feedback && submit(feedback.recommended, true)} className="px-4 py-2 text-sm rounded-lg bg-secondary disabled:opacity-40">{busy ? "提交中…" : "提交体验意见"}</button>
      {!feedback && <p className="text-xs text-muted-foreground">请先选择推荐或不推荐。</p>}
    </div>}
    {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
    {message && <p role="status" className="text-xs text-muted-foreground">{message}</p>}
  </section>;
}
