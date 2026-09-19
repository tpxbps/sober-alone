import { BookOpen, ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";

function scriptExcerpt(summary: string | undefined, content: string): string {
  return (summary?.trim() || content)
    .replace(/^#{1,6}\s+.*$/gm, "")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[*_`>#|]/g, "")
    .replace(/\s+/g, " ").trim().slice(0, 220);
}

export function PersonalScriptHint({ name, summary, content, onOpen, className }: {
  name?: string; summary?: string; content: string; onOpen: () => void; className?: string;
}) {
  return (
    <aside data-personal-script-hint aria-label="个人剧本阅读提醒"
      className={cn("personal-script-hint relative rounded-xl border border-primary/40 bg-card/95 p-4 shadow-xl backdrop-blur-xl", className)}>
      <div className="flex items-center gap-2 text-primary">
        <BookOpen className="size-4 shrink-0" />
        <p className="font-serif text-sm font-semibold">{name ? `${name}的个人剧本` : "我的个人剧本"}</p>
      </div>
      <p className="mt-2 line-clamp-3 text-xs leading-relaxed text-muted-foreground">{scriptExcerpt(summary, content)}</p>
      <button type="button" onClick={onOpen}
        className="mt-3 flex min-h-9 w-full items-center justify-center gap-2 rounded-md border border-primary/30 bg-primary/10 px-3 text-sm text-primary hover:bg-primary/20 focus-visible:outline-2 focus-visible:outline-primary">
        阅读我的剧本 <ArrowUpRight className="size-4" />
      </button>
      <span aria-hidden className="absolute -bottom-1.5 right-5 size-3 rotate-45 border-b border-r border-primary/40 bg-card" />
    </aside>
  );
}
