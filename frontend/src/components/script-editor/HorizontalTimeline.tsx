import { useEffect, useRef } from "react";
import { Check, CircleDot, Loader2 } from "lucide-react";
import { WORKFLOW_PHASES, getPhaseFromStep } from "@/types/editor";

interface HorizontalTimelineProps {
  currentStep: string;
  isComplete?: boolean;
  isWorking?: boolean;
  onNodeClick?: (phaseIndex: number) => void;
  viewingPhase?: string | null;
  workflowMode?: "create" | "edit";
}

export function HorizontalTimeline({
  currentStep,
  isComplete = false,
  isWorking = false,
  onNodeClick,
  viewingPhase,
  workflowMode = "create",
}: HorizontalTimelineProps) {
  const phases = workflowMode === "edit" ? WORKFLOW_PHASES.slice(4) : WORKFLOW_PHASES;
  const phaseOrder = phases.map((phase) => phase.phase);
  const currentPhase = getPhaseFromStep(currentStep);
  const currentIndex = phaseOrder.indexOf(currentPhase);
  const strip = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = strip.current;
    if (!element) return;
    const revealActive = () => {
      const active = element.querySelector<HTMLElement>("[data-phase-active]");
      if (!active) return;
      const viewport = element.getBoundingClientRect(), item = active.getBoundingClientRect();
      if (item.left < viewport.left || item.right > viewport.right) {
        element.scrollTo({ left: element.scrollLeft + item.left + item.width / 2 - viewport.left - viewport.width / 2, behavior: "instant" });
      }
    };
    revealActive();
    const resize = new ResizeObserver(revealActive);
    resize.observe(element);
    return () => resize.disconnect();
  }, [currentPhase, viewingPhase]);

  return (
    <div ref={strip} data-workflow-timeline className="flex items-center gap-1 overflow-x-auto py-3 px-1 scrollbar-thin">
      {phases.map((phase, index) => {
        const isCompleted = currentIndex > index;
        const isCurrent = currentIndex === index;
        // When workflow is complete and this is the last phase, show checkmark
        const isPhaseDone =
          isCompleted ||
          (isCurrent && isComplete && index === phaseOrder.length - 1);
        const isPending = currentIndex < index;
        const isViewing = viewingPhase === phase.phase;
        const isClickable = !isPending && !!onNodeClick;

        return (
          <div key={phase.phase} className="flex items-center shrink-0">
            {/* Step card */}
            <button
              type="button"
              disabled={!isClickable}
              aria-current={isCurrent ? "step" : undefined}
              data-phase-active={(viewingPhase ? isViewing : isCurrent) || undefined}
              onClick={() =>
                isClickable && onNodeClick?.(WORKFLOW_PHASES.indexOf(phase))
              }
              className={`
                relative px-3 py-2 rounded-lg border text-left transition-all min-w-[100px]
                ${isClickable ? "cursor-pointer hover:brightness-110" : ""}
                ${
                  isViewing
                    ? "border-primary bg-primary/20 ring-1 ring-primary/30"
                    : isPhaseDone
                    ? "border-success/30 bg-success/5"
                    : isCurrent
                    ? "border-primary bg-primary/10"
                    : "border-border/50 bg-card/50"
                }
              `}
            >
              {/* Title row */}
              <div className="flex items-center gap-1.5">
                {isPhaseDone ? (
                  <Check className="w-3.5 h-3.5 text-success shrink-0" />
                ) : isCurrent ? (
                  isWorking ? <Loader2 className="w-3.5 h-3.5 text-primary animate-spin motion-reduce:animate-none shrink-0" /> : <CircleDot className="w-3.5 h-3.5 text-primary shrink-0" />
                ) : (
                  <div className="w-3.5 h-3.5 rounded-full border border-border/50 shrink-0" />
                )}
                <span
                  className={`text-xs font-medium truncate ${
                    isPhaseDone
                      ? "text-success"
                      : isCurrent
                      ? "text-primary"
                      : "text-muted-foreground"
                  }`}
                >
                  {phase.label}
                </span>
                {phase.isAuto && (
                  <span
                    className={`text-[9px] px-1 py-0 rounded shrink-0 ${
                      isCurrent || isPhaseDone
                        ? "text-primary bg-primary/10"
                        : "text-muted-foreground bg-secondary/50"
                    }`}
                  >
                    自动
                  </span>
                )}
              </div>

              {/* Description */}
              <p className="text-[10px] text-muted-foreground mt-0.5 leading-tight line-clamp-2">
                {phase.desc}
              </p>
            </button>

            {/* Arrow connector */}
            {index < phases.length - 1 && (
              <div
                className={`mx-1 w-4 h-px ${
                  isPhaseDone ? "bg-success/40" : "bg-border/30"
                }`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
