import { Info } from 'lucide-react';
import type { BuildReport, Profile } from '@/api';
import { Tag } from '@/components/bayle/badge';
import { modName, reasonText, splitWhat } from './explain';

/* ------------------------------------------------------------------ not merged */

/** Whole files, stated limits, and changes the player chose to play without. Nothing to decide here, so it is quiet. */
export function NotMerged({ profile: p, build: b }: { profile: Profile; build: BuildReport }) {
  const whole = b.clashes.filter((c) => c.unsupported);
  const bases = b.baseline.exceptions;
  const without = b.dropped.filter((d) => d.accepted);
  if (!whole.length && !bases.length && !without.length) return null;
  return (
    <section aria-label="Not merged" className="flex flex-col gap-2">
      <h2 className="m-0 text-section font-semibold">Not merged <span className="font-normal text-t3">({whole.length + bases.length + without.length})</span></h2>
      <ul className="m-0 list-none overflow-hidden rounded-lg border border-line2 bg-panel p-0 text-ui">
        {whole.map((c) => (
          <li key={c.id} className="flex items-start gap-3 border-b border-line px-4 py-2 last:border-b-0">
            <Tag tone="vio">Whole file</Tag>
            <span><span className="font-mono">{c.file}</span>: {modName(p, c.winnerId)}'s copy is used ({reasonText(c, b)}). Whether it works with {c.sides.filter((s) => s.modId !== c.winnerId).map((s) => modName(p, s.modId)).join(', ')} is not known.</span>
          </li>
        ))}
        {without.map((d) => (
          <li key={d.id} className="flex items-start gap-3 border-b border-line px-4 py-2 last:border-b-0">
            <Tag>Left out</Tag>
            <span className="flex-1">{modName(p, d.modId)}: {splitWhat(d.what).plain.replace(/^its /, '')}. You chose to play without it.</span>
          </li>
        ))}
        {bases.map((e) => (
          <li key={e.modId} className="flex items-start gap-3 border-b border-line px-4 py-2 last:border-b-0">
            <Info className="mt-0.5 size-4 shrink-0 text-info" />
            <span>{modName(p, e.modId)} {e.base === 'unknown' ? 'does not say what it was made against' : `was made against ${e.base.mod}`}. It is compared against {b.baseline.game} anyway, so some of its changes may not mean what its author meant.</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
