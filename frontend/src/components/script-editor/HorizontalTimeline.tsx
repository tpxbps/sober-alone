import { Check, Loader2 } from "lucide-react";
import { WORKFLOW_PHASES, getPhaseFromStep } from "@/types/editor";

interface HorizontalTimelineProps {
  currentStep: string;
  isComplete?: boolean;
  onNodeClick?: (phaseIndex: number) => void;
  viewingPhase?: string | null;
}

const PHASE_ORDER = WORKFLOW_PHASES.map((p) => p.phase);

export function HorizontalTimeline({
  currentStep,
  isComplete = false,
  onNodeClick,
  viewingPhase,
}: HorizontalTimelineProps) {
  const currentPhase = getPhaseFromStep(currentStep);
  const currentIndex = PHASE_ORDER.indexOf(currentPhase);

  return (
    <div className="flex items-center gap-1 overflow-x-auto py-3 px-1 scrollbar-thin">
      {WORKFLOW_PHASES.map((phase, index) => {
        const isCompleted = currentIndex > index;
        const isCurrent = currentIndex === index;
        // When workflow is complete and this is the last phase, show checkmark
        const isPhaseDone =
          isCompleted ||
          (isCurrent && isComplete && index === PHASE_ORDER.length - 1);
        const isPending = currentIndex < index;
        const isViewing = viewingPhase === phase.phase;
        const isClickable = !isPending && !!onNodeClick;

        return (
          <div key={phase.phase} className="flex items-center shrink-0">
            {/* Step card */}
            <div
              onClick={() => isClickable && onNodeClick?.(index)}
              className={`
                relative px-3 py-2 rounded-lg border text-left transition-all min-w-[100px]
                ${isClickable ? "cursor-pointer hover:brightness-110" : ""}
                ${
                  isViewing
                    ? "border-primary bg-primary/20 ring-1 ring-primary/30"
                    : isPhaseDone
                    ? "border-green-500/30 bg-green-500/5"
                    : isCurrent
                    ? "border-primary bg-primary/10"
                    : "border-border/30 bg-card/50 opacity-50"
                }
              `}
            >
              {/* Title row */}
              <div className="flex items-center gap-1.5">
                {isPhaseDone ? (
                  <Check className="w-3.5 h-3.5 text-green-500 shrink-0" />
                ) : isCurrent ? (
                  <Loader2 className="w-3.5 h-3.5 text-primary animate-spin shrink-0" />
                ) : (
                  <div className="w-3.5 h-3.5 rounded-full border border-border/50 shrink-0" />
                )}
                <span
                  className={`text-xs font-medium truncate ${
                    isPhaseDone
                      ? "text-green-500"
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
                        ? "text-primary/40 bg-primary/5"
                        : "text-muted-foreground/50 bg-secondary/30"
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
            </div>

            {/* Arrow connector */}
            {index < WORKFLOW_PHASES.length - 1 && (
              <div
                className={`mx-1 w-4 h-px ${
                  isPhaseDone ? "bg-green-500/40" : "bg-border/30"
                }`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
