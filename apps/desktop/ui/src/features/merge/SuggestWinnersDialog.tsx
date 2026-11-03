import { useState } from 'react';
import { ChevronDown, ChevronRight, Wand2 } from 'lucide-react';
import type { ModSurvival, Profile, Suggestion } from '@/api';
import { Dialog } from '@/components/bayle/overlay';
import { Checkbox } from '@/components/bayle/controls';
import { Button } from '@/components/ui/button';
import { useCall, useOrderSuggestion } from '@/data/hooks';
import { cn } from '@/lib/utils';
import { modName } from './explain';

/**
 * "Who should win?" Bayle compares what every mod changes and suggests a load
 * order where mods can move, and kind rules where they can't (a mod that has
 * to load last). Each suggestion shows its reason and its trade: who gains
 * which pieces, who gives them up. Nothing changes until Apply.
 */
export function SuggestWinnersDialog({ profile: p, open, onOpenChange }: { profile: Profile; open: boolean; onOpenChange: (o: boolean) => void }) {
  const q = useOrderSuggestion(open ? p.id : undefined);
  const data = q.data;
  return (
    <Dialog open={open} onOpenChange={onOpenChange} width={620} title="Who should win?"
      description="Bayle compared what every mod changes. A mod that changes a few things exists for those things, so it should keep them. Nothing changes until you apply.">
      {!data ? <p className="m-0 py-6 text-center text-ui text-t3">Comparing what each mod changes…</p>
        : <Body key={data.suggestions.map((s) => s.id).join()} profile={p} survival={data.survival} suggestions={data.suggestions} leftAlone={data.leftAlone} onDone={() => onOpenChange(false)} />}
    </Dialog>
  );
}

function Body({ profile: p, survival, suggestions, leftAlone, onDone }: { profile: Profile; survival: ModSurvival[]; suggestions: Suggestion[]; leftAlone: string[]; onDone: () => void }) {
  const [on, setOn] = useState(() => new Set(suggestions.map((s) => s.id)));
  const [busy, setBusy] = useState(false);
  const call = useCall();
  const chosen = suggestions.filter((s) => on.has(s.id));
  const delta = (id: string) => chosen.flatMap((s) => s.effect).filter((e) => e.modId === id).reduce((n, e) => n + e.delta, 0);
  const rows = [...survival].sort((x, y) => x.kept / x.total - y.kept / y.total);

  const apply = async () => {
    setBusy(true);
    for (const s of chosen) {
      if (s.kind === 'order') await call((a) => a.reorderMods(p.id, s.modKind, s.orderedIds));
      else await call((a) => a.setRule(p.id, s.family, s.order, s.coupled));
    }
    const pieces = chosen.reduce((n, s) => n + s.changes.length, 0);
    await call(async () => undefined, { title: `Applied ${chosen.length} suggestion${chosen.length === 1 ? '' : 's'}`, detail: `${pieces} piece${pieces === 1 ? '' : 's'} change winner at the next rebuild. Undo each in Activity.` });
    setBusy(false); onDone();
  };

  return (
    <div className="flex flex-col gap-4">
      <section aria-label="How much of each mod gets in" className="flex flex-col gap-1.5">
        <h3 className="m-0 text-ui font-semibold">How much of each mod gets in</h3>
        <ul className="m-0 list-none overflow-hidden rounded-lg border border-line2 p-0 text-ui">
          {rows.map((r) => {
            const d = delta(r.modId);
            return (
              <li key={r.modId} data-survival={r.modId} className="flex flex-wrap items-baseline gap-x-3 border-b border-line px-3 py-1.5 last:border-b-0">
                <span className="min-w-0 flex-1 truncate font-medium">{modName(p, r.modId)}</span>
                <span className="tabular-nums text-t2">{r.kept.toLocaleString('en-US')} of {r.total.toLocaleString('en-US')}</span>
                {d !== 0 && <span className={cn('tabular-nums font-semibold', d > 0 ? 'text-ok' : 'text-t3')}>→ {(r.kept + d).toLocaleString('en-US')}</span>}
                {r.dropped > 0 && <span className="w-full text-xs text-t4">{r.dropped} left out, so no order can bring {r.dropped === 1 ? 'it' : 'them'} back</span>}
              </li>
            );
          })}
        </ul>
      </section>

      {suggestions.length ? (
        <section aria-label="Suggestions" className="flex flex-col gap-1.5">
          <h3 className="m-0 text-ui font-semibold">Suggestions</h3>
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {suggestions.map((s) => <SuggestionRow key={s.id} profile={p} s={s} checked={on.has(s.id)} onChecked={(c) => { const n = new Set(on); if (c) n.add(s.id); else n.delete(s.id); setOn(n); }} />)}
          </ul>
        </section>
      ) : <p className="m-0 rounded-lg border border-line2 px-3 py-2.5 text-ui">Nothing to suggest. Every mod already keeps what it can.</p>}

      {leftAlone.length > 0 && (
        <section aria-label="Left alone" className="flex flex-col gap-1">
          <h3 className="m-0 text-ui font-semibold text-t2">Left alone</h3>
          <ul className="m-0 list-disc pl-4 text-xs text-t3">{leftAlone.map((x) => <li key={x}>{x}</li>)}</ul>
        </section>
      )}

      <div className="flex items-center justify-end gap-2 border-t border-line pt-3">
        <Button variant="ghost" onClick={onDone}>{suggestions.length ? 'Keep mine' : 'Close'}</Button>
        {suggestions.length > 0 && <Button variant="primary" icon={<Wand2 />} disabled={busy || !chosen.length} onClick={() => void apply()}>Apply {chosen.length || ''}</Button>}
      </div>
    </div>
  );
}

function SuggestionRow({ profile: p, s, checked, onChecked }: { profile: Profile; s: Suggestion; checked: boolean; onChecked: (c: boolean) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <li data-suggestion={s.id} className={cn('rounded-lg border px-3 py-2.5', checked ? 'border-accent/40 bg-panel' : 'border-line2')}>
      <label className="flex items-start gap-2.5">
        <Checkbox checked={checked} onCheckedChange={(c) => onChecked(!!c)} aria-label={s.title} />
        <span className="min-w-0">
          <span className="block text-body font-medium">{s.title}</span>
          <span className="mt-0.5 block text-xs text-t3">{s.reason}</span>
          {s.kind === 'order' && <span className="mt-1 block text-xs text-t2">New order: {s.orderedIds.filter((id) => s.moves.some((m) => m.modId === id)).map((id) => modName(p, id)).join(', then ')}</span>}
        </span>
      </label>
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="mt-1.5 ml-[26px] flex items-center gap-1 text-xs text-t3 hover:text-t1">
        {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}{s.changes.length === 1 ? '1 piece changes' : `${s.changes.length} pieces change`} winner
      </button>
      {open && (
        <ul className="m-0 mt-1 ml-[26px] list-none p-0 text-xs">
          {s.changes.map((c) => <li key={c.clashId} className="flex items-center gap-2 py-0.5"><span className="min-w-0 flex-1 truncate">{c.piece}</span><span className="text-t4 line-through">{modName(p, c.fromId)}</span><span className="text-t4">→</span><span className="font-medium">{modName(p, c.toId)}</span></li>)}
        </ul>
      )}
    </li>
  );
}
