import { useState, type ReactNode } from 'react';
import { History, Trash2 } from 'lucide-react';
import type { BuildReport, Clash, ClashResolution, Profile } from '@/api';
import { ConfirmDialog } from '@/components/bayle/overlay';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { cn } from '@/lib/utils';
import { modName, reasonText, ruleFor } from './explain';

/**
 * One piece as a stack, the way DevTools shows a CSS property: every mod's
 * value, the one the game uses on top, the others struck through, each with
 * why. Under it, one choice (a radio group): follow the rule or load order,
 * use one mod, or (for rows both mods added) keep both, which asks first.
 * `footer` holds the closing action when the piece came from Needs you.
 */
export function PieceStack({ clash: c, build: b, profile: p, pending, onResolve, footer }: { clash: Clash; build: BuildReport; profile: Profile; pending: boolean; onResolve: (r: ClashResolution, pickedId?: string) => void; footer?: ReactNode }) {
  const [confirmBoth, setConfirmBoth] = useState(false);
  const pos = (id: string) => p.mods.findIndex((m) => m.id === id);
  const both = c.reason === 'both';
  const fixed = b.choices === false; // load order decides; there is nothing to choose
  const rows = [...c.sides].sort((x, y) => (x.modId === c.winnerId ? -1 : y.modId === c.winnerId ? 1 : pos(y.modId) - pos(x.modId)));
  const r = ruleFor(b, c.family);
  const fallback = r ? 'Follow your rule' : 'Follow load order';
  const later = [...c.sides].sort((x, y) => pos(x.modId) - pos(y.modId)).pop()!.modId;
  const value = c.unresolved ? '' : c.resolution === 'both' ? 'both' : c.resolution === 'pick' ? `pick:${c.pickedId}` : 'order';
  const choose = (v: string) => {
    if (!v || v === value) return;
    if (v === 'both') setConfirmBoth(true);
    else if (v === 'order') onResolve('order');
    else onResolve('pick', v.slice(5));
  };

  return (
    <div className="flex flex-col gap-2.5">
      {c.conflict === 'delete-edit' && (
        <p className="m-0 flex items-start gap-2 text-xs text-warn"><Trash2 className="mt-0.5 size-3.5 shrink-0" />One mod removes what the other changes, so both can't happen. Pick which one the game gets.</p>
      )}
      <ol className="m-0 list-none overflow-hidden rounded-sm border border-line p-0">
        {rows.map((s) => {
          const wins = !c.unresolved && (both || s.modId === c.winnerId);
          return (
            <li key={s.modId} className={cn('grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-3 border-b border-line px-3 py-1.5 last:border-b-0 max-[560px]:grid-cols-1 max-[560px]:gap-0.5', wins && 'bg-ok-bg/30')}>
              <div className="min-w-0">
                <span className={cn('text-ui', wins ? 'font-semibold' : 'text-t3')}>{modName(p, s.modId)}</span>
                <span className={cn('ml-2 font-mono text-code break-words', wins ? 'text-t1' : c.unresolved ? 'text-t2' : 'text-t4 line-through decoration-t4')}>{s.value}</span>
              </div>
              <span className={cn('text-caption whitespace-nowrap', wins ? 'text-ok' : 'text-t4')}>
                {c.unresolved ? 'waiting for you' : wins ? (both ? 'kept, moved to a new id' : `used · ${reasonText(c, b)}`) : `not used · ${modName(p, c.winnerId)} wins`}
              </span>
            </li>
          );
        })}
      </ol>
      {c.rebase && (
        <p className="m-0 flex items-start gap-2 text-xs text-t3"><History className="mt-0.5 size-3.5 shrink-0 text-info" />
          {modName(p, c.rebase.modId)} was made when the game had {c.rebase.wasVanilla} here; {b.baseline.game} has {c.rebase.nowVanilla}. Its value may not mean what its author meant.</p>
      )}
      {c.unsupported && <p className="m-0 text-xs text-t3">This kind of file is not merged: one mod's whole file is used. Whether the two work together is not known.</p>}
      {!fixed && <div className={cn('flex flex-col gap-1.5', pending && 'pointer-events-none opacity-60')}>
        <span id={`pick-${c.id}`} className="text-caption font-medium text-t3">Which one does the game get?</span>
        <ToggleGroup type="single" value={value} onValueChange={choose} aria-labelledby={`pick-${c.id}`} className="max-w-full flex-wrap">
          {!c.unresolved && <ToggleGroupItem value="order">{fallback}</ToggleGroupItem>}
          {c.sides.map((s) => <ToggleGroupItem key={s.modId} value={`pick:${s.modId}`}>{modName(p, s.modId)}</ToggleGroupItem>)}
          {c.canKeepBoth && !c.unsupported && <ToggleGroupItem value="both">Keep both…</ToggleGroupItem>}
        </ToggleGroup>
      </div>}
      {footer}
      <ConfirmDialog open={confirmBoth} onOpenChange={setConfirmBoth} confirmLabel="Keep both, I understand" title={`Keep both versions of ${c.piece}?`}
        description={`${modName(p, later)}'s row moves to the next free id, and the references to it that Bayle knows about are rewritten. Any reference it does not know about would point at nothing. This is not checked in game. Undo in Activity puts it back.`}
        onConfirm={() => onResolve('both')} />
    </div>
  );
}
