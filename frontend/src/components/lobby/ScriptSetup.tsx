import { useEffect, useState } from "react";
import * as Select from "@radix-ui/react-select";
import { ArrowLeft, ArrowRight, Check, ChevronDown, Clock3, LoaderCircle, Users, Zap } from "lucide-react";
import { getScriptDisplayTags } from "@/lib/scriptDisplay";
import { DIFFICULTY_COLORS, type Script } from "@/types/game";
import { ScriptRating } from "@/components/game/ScriptRating";
import { StoryCover } from "./StoryCover";
import { useScriptSetup } from "./useScriptSetup";

export function ScriptSetup({ script, quiet, onBack, onStartGame, onBusyChange }: {
  script: Script; quiet: boolean; onBack: (keyboard?: boolean) => void; onStartGame: (id: string) => void; onBusyChange: (busy: boolean) => void;
}) {
  const setup = useScriptSetup(script.script_id, quiet, onStartGame);
  const [expanded, setExpanded] = useState<string | null>(null);
  const busy = setup.phase !== "idle";
  useEffect(() => { onBusyChange(busy); return () => onBusyChange(false); }, [busy, onBusyChange]);
  const difficulty = DIFFICULTY_COLORS[script.difficulty] || DIFFICULTY_COLORS[1];
  return <>
    <section inert={busy} className="script-setup" aria-label={`剧本详情 ${script.title}`} aria-busy={busy}>
      <button className="setup-back" onClick={event => onBack(event.detail === 0)} disabled={busy}><ArrowLeft size={16} />返回列表</button>
      <div className="setup-grid">
        <div className="setup-story">
          <div className="setup-metadata">
          <h1 tabIndex={-1} className="setup-title">{script.title}</h1>
          <div className="setup-tags">{getScriptDisplayTags(script).map(tag => <span key={tag}>{tag}</span>)}</div>
          <div className="setup-stats"><span><Users size={14} />{script.player_count} 个角色</span><span><Clock3 size={14} />{script.estimated_duration > 0 ? `约 ${script.estimated_duration} 分钟` : "时长待定"}</span><span>{difficulty.label}</span></div>
          <p className="setup-overview">{script.overview || script.description}</p>
          {script.description && script.description !== script.overview && <details className="setup-full-description"><summary>完整简介</summary><p>{script.description}</p></details>}
          <div className="setup-rating"><ScriptRating script={script} context="detail" disabled={busy} /></div>
          </div>
          <div className="setup-cover" aria-hidden="true">
            <div className="setup-portal"><StoryCover className="setup-cover-veil" src={script.cover_image_url} /><StoryCover className="setup-cover-art" src={script.cover_image_url} loading="eager" /></div>
          </div>
        </div>
        <div className="setup-casting">
          <div className="setup-casting-heading"><h2>选择你的角色</h2><button onClick={setup.refreshHealth} disabled={setup.refreshing || busy} aria-label={setup.refreshing ? "模型测速中" : "重新进行模型测速"} className="setup-health"><Zap size={13} />{setup.refreshing ? "测速中" : "模型测速"}</button></div>
          {setup.healthMessage && <p className="setup-health-message" role="status">{setup.healthMessage}</p>}
          {setup.loading ? <p className="setup-loading" role="status"><LoaderCircle className="animate-spin" size={18} />加载角色与模型…</p> : setup.loadError ? <div role="alert" className="setup-error">{setup.loadError}<button onClick={setup.reload}>重新加载</button></div> : <>
            <div className="setup-characters" role="group" aria-label="选择扮演角色">
              {setup.characters.map(char => {
                const selected = setup.human === char.character_id;
                const modelId = setup.assignments[char.character_id] || "";
                const health = setup.health[modelId];
                return <div key={char.character_id} className={`setup-character${selected ? " is-selected" : ""}`}>
                  <button className="setup-character-choice" aria-label={`扮演 ${char.name}`} aria-pressed={selected} disabled={busy} onClick={() => setup.selectHuman(char.character_id)}>
                    <img className="setup-avatar" src={char.avatar_url || "/lobby/dragon.png"} alt="" onError={event => { event.currentTarget.onerror = null; event.currentTarget.src = "/lobby/dragon.png"; }} />
                    <span className="setup-character-info"><span className="setup-character-name">{char.name}<span>{[char.gender, char.age != null ? `${char.age} 岁` : ""].filter(Boolean).join(" · ")}</span></span><span className="setup-character-profile">{char.profile || char.occupation || "暂无角色介绍"}</span></span>
                    {selected && <Check className="setup-selected-icon" size={17} />}
                  </button>
                  {char.profile && <button className="setup-profile-toggle" aria-expanded={expanded === char.character_id} onClick={() => setExpanded(expanded === char.character_id ? null : char.character_id)}>{expanded === char.character_id ? "收起介绍" : "角色介绍"}<ChevronDown size={12} /></button>}
                  {expanded === char.character_id && <p className="setup-profile-full">{char.profile}</p>}
                  {setup.human && !selected && <div className="setup-model">
                    <label id={`model-label-${char.character_id}`}>AI 扮演模型</label>
                    {setup.models.length ? <Select.Root value={modelId} onValueChange={value => setup.selectModel(char.character_id, value)} disabled={busy}>
                      <Select.Trigger className="setup-model-trigger" aria-label={`${char.name}的 AI 模型`}><Select.Value placeholder="选择模型" /><Select.Icon><ChevronDown size={14} /></Select.Icon></Select.Trigger>
                      <Select.Portal><Select.Content className="setup-model-menu" position="popper" sideOffset={5} collisionPadding={12}><Select.Viewport>
                        {setup.models.map(model => <Select.Item aria-label={model.name} key={model.id} value={model.id} className="setup-model-option"><Select.ItemText>{model.name}</Select.ItemText><span>{setup.health[model.id]?.status === "normal" ? "" : setup.health[model.id]?.status === "slow" ? "响应较慢" : setup.health[model.id]?.status === "timeout" ? "测速超时" : setup.health[model.id]?.status === "unavailable" ? "当前不可用" : ""}</span><Select.ItemIndicator><Check size={13} /></Select.ItemIndicator></Select.Item>)}
                      </Select.Viewport></Select.Content></Select.Portal>
                    </Select.Root> : <p role="status" className="setup-model-warning">暂不可分配 AI 模型：{setup.modelReason}</p>}
                    {health && health.status !== "normal" && <p role="status" className="setup-model-warning">{health.status === "unavailable" ? "模型暂不可用，建议选择其他模型" : health.message}</p>}
                  </div>}
                </div>;
              })}
            </div>
            {setup.modelReason && <p className="setup-model-warning" role="status">{setup.modelReason}<button onClick={setup.reload}>重新加载</button></p>}
            {setup.error && <p role="alert" className="setup-error">{setup.error}</p>}
            <button className="setup-enter" disabled={!setup.canStart || busy} onClick={setup.start}>{busy ? <><LoaderCircle className="animate-spin" size={17} />正在准备故事…</> : <>{setup.error ? "重试进入故事" : "走进故事"}<ArrowRight size={18} /></>}</button>
            {!setup.human && <p className="setup-selection-hint">请先选择你要扮演的角色</p>}
          </>}
        </div>
      </div>
    </section>
    {busy && <div className={`game-entry-overlay ${setup.phase}${quiet ? " is-quiet" : ""}`} role="status" aria-live="polite"><span>正在准备故事…</span></div>}
  </>;
}
