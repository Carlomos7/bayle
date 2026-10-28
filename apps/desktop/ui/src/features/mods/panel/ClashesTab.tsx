import { GitMerge } from 'lucide-react';
import type { Mod } from '@/api';
import { Button } from '@/components/ui/button';
import { useBuild } from '@/data/hooks';
import { OUTCOME } from '@/features/merge/words';
import { cn } from '@/lib/utils';
import { useMods } from '../controller';

/* ------------------------------------------------------------------ Clashes tab */

/** Where this mod's changes meet another mod's, and how each one ended. Settling happens on Merge. */
export function ClashesTab({ mod: m }: { mod: Mod }) {
  const c = useMods();
  const build = useBuild(c.profile.id);
  const b = build.data;
  const name = (id: string) => c.profile.mods.find((x) => x.id === id)?.name ?? id;
  const clashes = (b?.clashes ?? []).filter((x) => x.sides.some((s) => s.modId === m.id));
  const dropped = (b?.dropped ?? []).filter((d) => d.modId === m.id);
  const cells = (b?.cells ?? []).filter((x) => x.modId === m.id);
  const survival = b?.survival?.find((x) => x.modId === m.id);
  const sum = (o: string) => cells.filter((x) => x.outcome === o).reduce((n, x) => n + x.count, 0);
  if (!b || b.state === 'none' || (!cells.length && !clashes.length && !dropped.length)) {
    return <p className="m-0 rounded-lg border border-dashed border-line2 px-4 py-5 text-center text-ui text-t3">No other mod changes the same files. Everything in {m.name} is used as it is.</p>;
  }
  return (
    <div className="flex flex-col gap-3">
      {survival && survival.total > 0 && (
        <p className="m-0 text-body"><b className="font-semibold tabular-nums">{survival.kept.toLocaleString('en-US')} of {survival.total.toLocaleString('en-US')}</b> changes get into the game{survival.lost.length ? `; ${survival.lost.length} lost to other mods` : ''}{survival.dropped ? `; ${survival.dropped} left out` : ''}.</p>
      )}
      <div className="flex flex-wrap gap-1.5">
        {(['merged', 'won', 'picked', 'lost', 'dropped', 'unsupported', 'unknown'] as const).filter((o) => sum(o) > 0).map((o) => (
          <span key={o} className={cn('inline-flex h-[22px] items-center gap-1 rounded-xs px-2 text-caption font-medium tabular-nums', OUTCOME[o].chip)}><b className="font-semibold">{sum(o).toLocaleString()}</b>{OUTCOME[o].label.toLowerCase()}</span>
        ))}
      </div>
      {dropped.length > 0 && (
        <ul className="m-0 list-none divide-y divide-line overflow-hidden rounded-lg border border-bad/35 p-0">
          {dropped.map((d) => <li key={d.id} className="px-3 py-2 text-ui"><b className="font-semibold text-bad">Dropped</b> · {d.what}<div className="text-xs text-t3">{d.reason} {d.fix}</div></li>)}
        </ul>
      )}
      {clashes.length > 0 && (
        <ul className="m-0 list-none divide-y divide-line overflow-hidden rounded-lg border border-line2 p-0">
          {clashes.map((x) => {
            const other = x.sides.find((s) => s.modId !== m.id);
            const winner = x.winnerId;
            const why = x.reason === 'pick' ? 'your pick' : x.reason === 'rule' || x.reason === 'coupled' ? 'your rule' : 'loads later';
            const mine = x.reason === 'both' ? 'both kept' : winner === m.id ? `yours, ${why}` : `lost to ${name(other?.modId ?? '')}, ${why}`;
            return (
              <li key={x.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 px-3 py-2 text-ui">
                <div className="min-w-0"><div className="truncate">{x.piece}</div><div className="truncate text-xs text-t3">{x.file} · with {name(other?.modId ?? '')}</div></div>
                <span className={cn('text-xs', winner === m.id || x.reason === 'both' ? 'text-ok' : 'text-warn')}>{mine}{x.needsReview ? ' · check' : ''}</span>
              </li>
            );
          })}
        </ul>
      )}
      <div><Button size="sm" icon={<GitMerge />} onClick={() => c.openMerge(m.id)}>{b.choices === false ? 'Open Merge' : 'Settle on Merge'}</Button></div>
    </div>
  );
}
