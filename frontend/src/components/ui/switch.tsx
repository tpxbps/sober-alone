import type { ComponentProps } from "react";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import { cn } from "@/lib/utils";

export function Switch({ className, compact = false, ...props }: ComponentProps<typeof SwitchPrimitive.Root> & { compact?: boolean }) {
  return <SwitchPrimitive.Root {...props} data-slot="switch"
    className={cn("relative shrink-0 rounded-full bg-secondary transition-colors data-[state=checked]:bg-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50", compact ? "h-5 w-9" : "h-6 w-11", className)}>
    <SwitchPrimitive.Thumb data-slot="switch-thumb" className={cn("block translate-x-0.5 rounded-full bg-foreground shadow-sm transition-transform data-[state=checked]:bg-primary-foreground", compact ? "h-4 w-4 data-[state=checked]:translate-x-[18px]" : "h-5 w-5 data-[state=checked]:translate-x-[22px]")} />
  </SwitchPrimitive.Root>;
}
