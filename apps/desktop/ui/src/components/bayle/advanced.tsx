import { useState, type ReactNode } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';

/**
 * The one door to the second level, the same on every page: a folded row
 * whose label says what is inside ("Advanced: the load-order board and every
 * clash"), never just "More". Closed by default; the state is per page view.
 */
export function Advanced({ label, children, defaultOpen = false, className, id }: { label: string; children: ReactNode; defaultOpen?: boolean; className?: string; id?: string }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section id={id} aria-label={label} className={cn('rounded-lg border border-dashed border-line2', open && 'border-solid', className)}>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-ui text-t2 hover:bg-hover">
        {open ? <ChevronDown className="size-4 text-t4" /> : <ChevronRight className="size-4 text-t4" />}
        <span className="font-medium text-t1">Advanced</span><span className="text-t3">{label}</span>
      </button>
      {open && <div className="flex flex-col gap-5 border-t border-line p-4">{children}</div>}
    </section>
  );
}
