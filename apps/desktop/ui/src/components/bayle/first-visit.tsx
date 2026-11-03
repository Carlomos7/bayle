import type { ReactNode } from 'react';
import { X } from 'lucide-react';
import { useUi } from '@/state/ui';
import { Button } from '@/components/ui/button';

/**
 * A one-time explainer at the top of a page, in plain words, gone for good
 * once dismissed. For the first visit to a page whose purpose isn't obvious;
 * not a tooltip, because tooltips only help people who already know where to hover.
 */
export function FirstVisit({ tipKey, title, children, action }: { tipKey: string; title: string; children: ReactNode; action?: ReactNode }) {
  const seen = useUi((s) => s.seenTips.includes(tipKey));
  const dismiss = useUi((s) => s.dismissTip);
  if (seen) return null;
  return (
    <div role="note" data-tip={tipKey} className="flex items-start gap-4 rounded-lg border border-accent/35 bg-accent-soft/40 px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="text-body font-semibold">{title}</div>
        <div className="mt-1 max-w-[70ch] text-ui leading-[1.5] text-t2">{children}</div>
        {action && <div className="mt-2">{action}</div>}
      </div>
      <Button size="sm" variant="ghost" icon={<X />} onClick={() => dismiss(tipKey)} aria-label="Got it, don't show this again">Got it</Button>
    </div>
  );
}
