import { useState } from 'react';
import { ChevronDown, ChevronRight, Trash2 } from 'lucide-react';
import type { BuildReport, Clash, Profile } from '@/api';
import { Tag } from '@/components/bayle/badge';
import { Button } from '@/components/ui/button';
import { useAction } from '@/data/hooks';
import { cn, plural } from '@/lib/utils';
import { modName, winsOver } from './explain';
import { FAMILY } from './words';

/* ------------------------------------------------------------------ rules list */

/** Every decision in one place, like npm overrides: kind rules (dormant ones too) and single picks. */
export function RulesList({ profile: p, build: b, onOpenPiece }: { profile: Profile; build: BuildReport; onOpenPiece: (c: Clash) => void }) {
  const [open, setOpen] = useState(false);
  const { run } = useAction();
  const picks = b.clashes.filter((c) => c.resolution === 'pick' || c.resolution === 'both');
  const n = b.rules.length + picks.length;
  return (
    <section aria-label="Your rules" className="rounded-lg border border-line2">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-ui hover:bg-hover">
        {open ? <ChevronDown className="size-4 text-t4" /> : <ChevronRight className="size-4 text-t4" />}
        <span className="font-medium">Your rules</span><span className="text-t3">{n ? `${plural(b.rules.length, 'kind rule')}, ${plural(picks.length, 'single pick')}` : 'none yet: everything follows load order'}</span>
      </button>
      {open && n > 0 && (
        <ul className="m-0 list-none border-t border-line p-0 text-ui">
          {b.rules.map((r) => (
            <li key={r.id} className={cn('flex items-center gap-3 border-b border-line px-4 py-2 last:border-b-0', r.dormant && 'text-t4')}>
              <span className="w-24 shrink-0 font-medium">{FAMILY[r.family].label}</span>
              <span className="min-w-0 flex-1 truncate">{winsOver(p, r.order)}{r.coupled?.length ? ` · with ${r.coupled.map((f) => FAMILY[f].label.toLowerCase()).join(', ')}` : ''}</span>
              {r.dormant && <Tag>waiting: a mod in it is off</Tag>}
              <Button size="sm" variant="ghost" icon={<Trash2 />} onClick={() => void run((a) => a.setRule(p.id, r.family, null))}>Remove</Button>
            </li>
          ))}
          {picks.map((c) => (
            <li key={c.id} className="flex items-center gap-3 border-b border-line px-4 py-2 last:border-b-0">
              <span className="w-24 shrink-0 text-t3">Single pick</span>
              <button type="button" onClick={() => onOpenPiece(c)} className="min-w-0 flex-1 truncate text-left hover:underline">{c.piece}: {c.reason === 'both' ? 'both kept' : modName(p, c.winnerId)}</button>
              <Button size="sm" variant="ghost" icon={<Trash2 />} onClick={() => void run((a) => a.resolveClash(p.id, c.id, 'order'))}>Remove</Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
