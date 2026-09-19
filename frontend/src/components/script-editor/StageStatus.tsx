import { Loader2 } from 'lucide-react';

export function StageStatus({ children }: { children: React.ReactNode }) {
  return <div className="px-5 py-3"><div role="status" aria-live="polite" aria-busy="true" className="flex items-center gap-2 text-sm text-muted-foreground">
    <Loader2 className="h-4 w-4 shrink-0 animate-spin motion-reduce:animate-none text-primary" />
    <span>{children}</span>
  </div></div>;
}
