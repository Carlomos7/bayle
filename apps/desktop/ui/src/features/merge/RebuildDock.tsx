import { useState } from 'react';
import { ArrowUpDown, ChevronDown, ChevronRight, CircleCheck, Download, Gamepad2, Hand, Minus, Plus, RefreshCw, ToggleLeft, Undo2, Wrench, type LucideIcon } from 'lucide-react';
import type { BuildChange, BuildReport, Profile } from '@/api';
import { Button } from '@/components/ui/button';
import { useAction, useSettings } from '@/data/hooks';
import { plural } from '@/lib/utils';
import { modName, needsCount, needsRebuild } from './explain';

const CHANGE_ICON: Record<BuildChange['kind'], LucideIcon> = {
  'mod-updated': Download, 'game-updated': Gamepad2, reordered: ArrowUpDown, toggled: ToggleLeft, 'setup-changed': Wrench, 'pick-changed': Hand, added: Plus, removed: Minus,
};


/* ------------------------------------------------------------------ rebuild dock */

/**
 * The one place to rebuild. Says why in a line (the game updated, 3 winners
 * change), opens to the full list like a Terraform plan, and offers to undo
 * only the player's own choices since the last build.
 */
export function RebuildDock({ profile: p, build: b }: { profile: Profile; build: BuildReport }) {
  const [open, setOpen] = useState(false);
  const { run, pending } = useAction();
  const settings = useSettings();
  if (!needsRebuild(b)) return null;
  const auto = settings.data?.launch.autoRebuild ?? true;
  const choices = b.choicesSinceBuild ?? 0;
  const waiting = b.clashes.filter((c) => c.unresolved);
  const why = [
    b.changes.length === 1 ? b.changes[0]!.title : b.changes.length ? `${b.changes.length} things changed` : '',
    b.pending.length ? `${plural(b.pending.length, 'winner')} change${b.pending.length === 1 ? 's' : ''}` : '',
  ].filter(Boolean).join(' · ');
  return (
    <div role="region" aria-label="Rebuild" data-unsaved-bar className="sticky bottom-0 z-[2] -mb-2 rounded-lg border border-line2 bg-raise shadow-pop animate-[rise_.14s_ease-out]">
      {open && (
        <div className="max-h-56 overflow-auto border-b border-line px-4 py-2.5 text-ui">
          {b.changes.length > 0 && <>
            <div className="mb-1 text-caption font-medium text-t3">What changed</div>
            <ul className="m-0 mb-2.5 flex list-none flex-col gap-1 p-0">
              {b.changes.map((c, i) => { const Icon = CHANGE_ICON[c.kind]; return <li key={i} className="flex items-start gap-2.5"><Icon className="mt-0.5 size-3.5 shrink-0 text-t3" /><span><span className="text-t1">{c.title}</span>{c.detail && <span className="text-t3"> {c.detail}</span>}</span></li>; })}
            </ul>
          </>}
          {b.pending.length > 0 && <>
            <div className="mb-1 text-caption font-medium text-t3">Who wins differently</div>
            <ul className="m-0 flex list-none flex-col p-0">
              {b.pending.map((x) => <li key={x.clashId} className="flex items-center gap-2 py-0.5"><span className="min-w-0 flex-1 truncate">{x.piece}</span><span className="text-t4 line-through">{modName(p, x.fromId) || 'none'}</span><span className="text-t4">→</span><span className="font-medium">{modName(p, x.toId) || 'both kept'}</span></li>)}
            </ul>
          </>}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5">
        <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex min-w-0 flex-1 flex-col items-start text-left">
          <span className="flex items-center gap-1.5 text-body font-semibold"><span className="size-1.5 rounded-full bg-accent" />Rebuild to apply{open ? <ChevronDown className="size-3.5 text-t3" /> : <ChevronRight className="size-3.5 text-t3" />}</span>
          <span className="text-xs text-t3 max-[560px]:hidden">{why}{auto ? '. Launch also does it first.' : ''}</span>
          {waiting.length > 0 && <span className="mt-0.5 text-xs text-warn max-[560px]:hidden">{waiting.map((c) => c.piece).join(', ')} still needs your decision. Until then the mod that loads later is used.</span>}
          {waiting.length > 0 && <span className="mt-0.5 hidden text-xs text-warn max-[560px]:block">{plural(waiting.length, 'decision')} still open</span>}
        </button>
        {choices > 0 && <Button variant="ghost" size="sm" icon={<Undo2 />} disabled={pending} onClick={() => void run((a) => a.discardPending(p.id))}><span className="max-[560px]:hidden">Undo my {plural(choices, 'choice')}</span><span className="hidden max-[560px]:inline">Undo</span></Button>}
        <Button variant="primary" size="sm" icon={<RefreshCw />} disabled={pending} onClick={() => void run((a) => a.rebuildMerged(p.id))}>Rebuild now</Button>
      </div>
    </div>
  );
}

/** Shown in place of Needs you once everything is handled but not built yet, so the end of the task is visible. */
export function AllSorted({ build: b }: { build: BuildReport }) {
  if (!needsRebuild(b) || needsCount(b) > 0) return null;
  return <p role="status" className="m-0 flex items-center gap-2 text-ui text-ok"><CircleCheck className="size-4" />Nothing needs you. Rebuild below to apply your changes, or just press Launch.</p>;
}
