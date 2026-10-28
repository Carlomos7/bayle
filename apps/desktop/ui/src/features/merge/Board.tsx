import { FEATURES } from '@/lib/features';
import { ArrowDown, Pin } from 'lucide-react';
import type { BuildCell, BuildReport, FileFamily, Mod, Outcome, Profile } from '@/api';
import { Tooltip } from '@/components/bayle/overlay';
import { cn } from '@/lib/utils';
import { FAMILY, OUTCOME, fmt } from './words';

export interface BoardFilter { modId?: string; family?: FileFamily }

/** Chips in one cell, worst outcome first so a problem is never hidden under a good number. */
function cellChips(cells: BuildCell[]) {
  return [...cells].filter((c) => c.count > 0).sort((a, b) => OUTCOME[b.outcome].weight - OUTCOME[a.outcome].weight);
}

function Chip({ outcome, count, active, onClick }: { outcome: Outcome; count: number; active: boolean; onClick: () => void }) {
  const o = OUTCOME[outcome];
  return (
    <Tooltip content={<span>{o.label}: {o.hint}</span>}>
      <button type="button" onClick={onClick} aria-pressed={active}
        className={cn('inline-flex h-[22px] items-center gap-1 rounded-xs px-1.5 text-caption font-medium tabular-nums whitespace-nowrap transition-[box-shadow,filter] hover:brightness-110', o.chip, active && 'shadow-[0_0_0_1.5px_var(--accent-ring)]')}>
        <b className="font-semibold">{fmt(count)}</b><span className="opacity-80">{o.label.toLowerCase()}</span>
      </button>
    </Tooltip>
  );
}

/**
 * The load-order board: one row per package, loads first at the top, the
 * last-loading mod pinned at the bottom. One column per kind of file that more than
 * one mod touches. Each cell says what happened to that mod's changes there.
 */
export function Board({ profile, build, filter, onFilter, onOpenMod }: { profile: Profile; build: BuildReport; filter: BoardFilter; onFilter: (f: BoardFilter) => void; onOpenMod: (id: string) => void }) {
  const packages = profile.mods.filter((m) => m.kind === 'package' && (m.enabled || m.missing));
  const fams = build.families;
  const cellsFor = (m: Mod, f: FileFamily) => build.cells.filter((c) => c.modId === m.id && c.family === f);
  const toggle = (modId: string, family: FileFamily) => onFilter(filter.modId === modId && filter.family === family ? {} : { modId, family });

  return (
    <div className="overflow-x-auto rounded-lg border border-line2 bg-panel">
      <table className="w-full border-collapse text-ui" aria-label="Load order and what happened to each mod's files">
        <thead>
          <tr className="border-b border-line2">
            <th scope="col" className="w-7 px-3 py-2.5 text-left text-micro font-medium text-t4"><ArrowDown className="size-3.5" aria-label="Loads first at the top" /></th>
            <th scope="col" className="min-w-[200px] px-2 py-2.5 text-left text-xs font-medium text-t3">Package</th>
            {fams.map((f) => (
              <th key={f} scope="col" className="px-2 py-2.5 text-left text-xs font-medium text-t3">
                <Tooltip content={FAMILY[f].hint}><span className="underline decoration-dotted decoration-line2 underline-offset-4">{FAMILY[f].label}</span></Tooltip>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {packages.map((m, i) => {
            const dimmed = !!m.missing;
            const rowActive = filter.modId === m.id;
            return (
              <tr key={m.id} className={cn('border-b border-line last:border-b-0', m.staysLast && 'border-t-2 border-t-line2 bg-[color-mix(in_srgb,var(--t1)_1.5%,var(--panel))]', rowActive && 'bg-accent-soft/40')}>
                <td className="px-3 py-2 text-right text-xs tabular-nums text-t4">{i + 1}</td>
                <td className="px-2 py-2">
                  <button type="button" onClick={() => onOpenMod(m.id)} className={cn('max-w-full truncate text-left font-medium hover:underline', dimmed && 'text-t4')}>{m.name}</button>
                  <div className="flex items-center gap-1.5 text-micro text-t4">
                    {m.staysLast ? <><Pin className="size-3" />Loads last: built on top of everything above</> : dimmed ? 'Folder missing, left out' : FEATURES.modVersions && m.version ? `v${m.version}` : ''}
                  </div>
                </td>
                {fams.map((f) => {
                  const chips = cellChips(cellsFor(m, f));
                  return (
                    <td key={f} className="px-2 py-2 align-top">
                      {chips.length ? (
                        <div className="flex flex-col items-start gap-1">
                          {chips.map((c) => <Chip key={c.outcome} outcome={c.outcome} count={c.count} active={rowActive && filter.family === f} onClick={() => toggle(m.id, f)} />)}
                        </div>
                      ) : <span className="text-micro text-t4">·</span>}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line px-3 py-2 text-caption text-t3">
        {(Object.keys(OUTCOME) as Outcome[]).map((o) => (
          <span key={o} className="inline-flex items-center gap-1.5"><span className={cn('size-2 rounded-xs', OUTCOME[o].chip.split(' ')[0])} />{OUTCOME[o].label}</span>
        ))}
        <span className="ml-auto">Lower in the list wins a clash. Click a number to see those pieces.</span>
      </div>
    </div>
  );
}
