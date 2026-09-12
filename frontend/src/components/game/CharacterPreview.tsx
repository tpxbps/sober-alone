import { useEffect, useState, type ReactNode } from "react";
import * as HoverCard from "@radix-ui/react-hover-card";
import { Eye } from "lucide-react";

function Portrait({ src, name }: { src?: string | null; name: string }) {
  const [failed, setFailed] = useState(false);
  return src && !failed ? <img src={src} alt={`${name}的人物形象`} onError={() => setFailed(true)}
    className="h-full w-full object-contain" loading="lazy" decoding="async" />
    : <div className="flex h-full min-h-40 w-full items-center justify-center bg-gradient-to-br from-primary/15 to-accent/15 text-5xl text-primary/60">{name.slice(0, 1)}</div>;
}

export function CharacterPreview({ name, src, children, details, side = "right" }: {
  name: string; src?: string | null; children: ReactNode; details?: ReactNode;
  side?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const [narrow, setNarrow] = useState(() => window.matchMedia("(max-width: 639px)").matches);
  useEffect(() => {
    const query = window.matchMedia("(max-width: 639px)");
    const update = () => setNarrow(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    if (!open) return;
    // Dialog and HoverCard currently use different Radix layer registries.
    // Consume Escape before either document listener dismisses its own layer.
    const close = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      setOpen(false);
    };
    window.addEventListener("keydown", close, true);
    return () => window.removeEventListener("keydown", close, true);
  }, [open]);
  return <HoverCard.Root open={open} onOpenChange={setOpen} openDelay={180} closeDelay={180}>
    <div className="relative min-w-0">
      <HoverCard.Trigger asChild>
        <div tabIndex={0} aria-label={`预览${name}的人物形象`} onFocus={() => setOpen(true)}
          onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}
          className="outline-none focus-visible:ring-2 focus-visible:ring-primary rounded-xl">
          {children}
        </div>
      </HoverCard.Trigger>
      <button type="button" aria-label={`查看${name}的人物形象`} aria-expanded={open}
        onClick={event => { event.stopPropagation(); setOpen(value => !value); }}
        className="absolute bottom-1 right-1 rounded-full bg-background/85 p-1.5 text-muted-foreground shadow-sm hover:text-primary [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:focus:opacity-100 [@media(hover:hover)]:hover:opacity-100">
        <Eye className="h-3 w-3" />
      </button>
    </div>
    <HoverCard.Portal>
      <HoverCard.Content side={narrow ? "top" : side} align="center" sideOffset={10} collisionPadding={details ? { top: 76, bottom: 12, left: 12, right: 12 } : 12}
        onEscapeKeyDown={event => { event.preventDefault(); setOpen(false); }}
        role="tooltip" aria-label={`${name}的人物预览`}
        onClick={event => event.stopPropagation()}
        className={`z-[100] overflow-hidden rounded-2xl border border-border bg-popover text-popover-foreground shadow-2xl max-w-[calc(100vw-24px)] ${details ? "w-[560px]" : "w-[280px]"}`}>
        <div className={details ? "flex" : ""} style={details ? { maxHeight: "min(400px, 75dvh, var(--radix-hover-card-content-available-height))" } : undefined}>
          <div className={details ? "w-[40%] shrink-0 bg-background/60" : "bg-background/60"}
            style={details ? undefined : { height: "min(380px, 65dvh, calc(var(--radix-hover-card-content-available-height) - 40px))" }}>
            <Portrait key={src} src={src} name={name} />
          </div>
          {details ? <div className="min-w-0 flex-1 overflow-y-auto p-4 text-sm scrollbar-thin">{details}</div>
            : <p className="border-t border-border/30 px-4 py-2 text-center text-sm font-medium">{name}</p>}
        </div>
      </HoverCard.Content>
    </HoverCard.Portal>
  </HoverCard.Root>;
}
