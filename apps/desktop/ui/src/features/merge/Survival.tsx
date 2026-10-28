import { Wand2 } from 'lucide-react';
import type { BuildReport, Profile } from '@/api';
import { Button, LinkButton } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { modName } from './explain';

/**
 * How much of each mod makes it into the game. A mod that loses a few of
 * thousands is fine; one that loses the few things it exists for is not, so
 * the share is what's shown, worst first. Suggest who wins sits beside it.
 */
export function Survival({ profile: p, build: b, onOpenMod, onSuggest }: { profile: Profile; build: BuildReport; onOpenMod: (id: string) => void; onSuggest: () => void }) {
  const rows = (b.survival ?? []).filter((r) => r.total > 0 && (r.lost.length || r.dropped || b.clashes.some((c) => c.sides.some((s) => s.modId === r.modId))))
    .sort((x, y) => x.kept / x.total - y.kept / y.total);
  if (!rows.length) return null;
  const n = (x: number) => x.toLocaleString('en-US');
  return (
    <section aria-label="How much of each mod gets in" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="m-0 flex-1 text-section font-semibold">How much of each mod gets in</h2>
        <Button size="sm" icon={<Wand2 />} onClick={onSuggest}>Suggest who wins</Button>
      </div>
      <ul className="m-0 list-none overflow-hidden rounded-lg border border-line2 bg-panel p-0 text-ui">
        {rows.map((r) => {
          const share = r.kept / r.total;
          const waiting = r.lost.filter((l) => b.clashes.find((c) => c.id === l.clashId)?.unresolved);
          const lost = r.lost.filter((l) => !waiting.includes(l));
          const lostTo = [...new Set(lost.map((l) => l.toId).filter(Boolean))].map((id) => modName(p, id));
          return (
            <li key={r.modId} data-survival={r.modId} className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-3 border-b border-line px-4 py-2 last:border-b-0">
              <LinkButton className="justify-self-start truncate font-medium text-t1" onClick={() => onOpenMod(r.modId)}>{modName(p, r.modId)}</LinkButton>
              <span className={cn('tabular-nums', share < 0.5 ? 'font-semibold text-bad' : share < 1 ? 'text-t2' : 'text-ok')}>{n(r.kept)} of {n(r.total)}</span>
              {(r.lost.length > 0 || r.dropped > 0) && (
                <span className="col-span-2 text-xs text-t3">
                  {lost.length > 0 && <>Loses {lost.slice(0, 2).map((l) => l.piece).join(', ')}{lost.length > 2 ? ` and ${lost.length - 2} more` : ''} to {lostTo.join(', ')}.</>}
                  {waiting.length > 0 && <span className="text-warn"> {waiting.map((l) => l.piece).join(', ')}: waiting for your decision.</span>}
                  {r.dropped > 0 && <> {n(r.dropped)} left out.</>}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
