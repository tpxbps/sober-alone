import { useMemo, useState } from "react";
import { AlertTriangle } from "lucide-react";
import type { AssetPlanItem } from "@/types/editor";

interface AssetPlanDialogProps {
  items: AssetPlanItem[];
  isLoading: boolean;
  onConfirm: (selectedIds: string[]) => Promise<void>;
}

export function AssetPlanDialog({ items, isLoading, onConfirm }: AssetPlanDialogProps) {
  const [selected, setSelected] = useState(
    () => new Set(items.filter((item) => item.default_selected).map((item) => item.id))
  );
  const groups = useMemo(
    () =>
      Object.entries(
        items.reduce<Record<string, AssetPlanItem[]>>((result, item) => {
          (result[item.phase_label] ||= []).push(item);
          return result;
        }, {})
      ),
    [items]
  );
  const inconsistent = items.filter(
    (item) => item.changed && item.available && !selected.has(item.id)
  );

  const toggle = (item: AssetPlanItem) => {
    if (!item.available || isLoading) return;
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(item.id)) next.delete(item.id);
      else next.add(item.id);
      return next;
    });
  };

  return (
    <div
      data-testid="asset-plan-scroll"
      className="h-full overflow-y-auto p-5 space-y-5 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent"
    >
      <div>
        <h2 className="text-lg font-bold">确认本次资源更新</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          已根据修改字段和资源缺失情况预选；未选中的资源会保留现有文件。
        </p>
      </div>
      {groups.map(([label, group]) => (
        <section key={label} className="space-y-2">
          <h3 className="text-sm font-semibold">{label}</h3>
          <div className="rounded-xl border border-border/60 divide-y divide-border/50">
            {group.map((item) => (
              <label
                key={item.id}
                className={`flex gap-3 p-3 ${item.available ? "cursor-pointer" : "opacity-50"}`}
              >
                <input
                  type="checkbox"
                  checked={selected.has(item.id)}
                  disabled={!item.available || isLoading}
                  onChange={() => toggle(item)}
                  className="mt-1 accent-primary"
                />
                <span className="min-w-0">
                  <span className="block text-sm font-medium">{item.label}</span>
                  <span className="block text-xs text-muted-foreground">
                    {item.available ? item.change_reason : item.unavailable_reason}
                  </span>
                </span>
              </label>
            ))}
          </div>
        </section>
      ))}
      {inconsistent.length > 0 && (
        <div className="flex gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-300">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>有 {inconsistent.length} 项依赖已变化但未选择，将保留旧资源，可能与新文本不一致。</span>
        </div>
      )}
      <button
        disabled={isLoading}
        onClick={() => onConfirm([...selected])}
        className="w-full rounded-lg bg-primary py-2.5 text-sm font-medium text-primary-foreground disabled:opacity-50"
      >
        {isLoading ? "保存并更新中…" : "确认保存并执行所选资源"}
      </button>
    </div>
  );
}
