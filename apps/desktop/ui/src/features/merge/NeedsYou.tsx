import { type ReactNode } from 'react';
import { Check, CircleAlert, TriangleAlert } from 'lucide-react';
import type { BuildReport, Clash, ClashResolution, DroppedChange, FileFamily, Profile } from '@/api';
import { Button, LinkButton } from '@/components/ui/button';
import { useAction, useCall } from '@/data/hooks';
import { useGo } from '@/app/nav';
import { cn, plural } from '@/lib/utils';
import { modName, needsOf, splitWhat } from './explain';
import { PieceStack } from './PieceStack';
import { FAMILY } from './words';

/* ------------------------------------------------------------------ needs you */

interface Item { id: string; tone: 'bad' | 'warn'; title: string; detail?: string; action: string; body: ReactNode }

/**
 * Only what needs a person, worst first. Each item opens right where it is,
 * with the buttons that settle it, and leaves the list once settled. One open
 * at a time, so there is always a single obvious next thing.
 */
export function NeedsYou({ profile: p, build: b, openId, openAt, onOpen, onChangeRule, onShowKind }: {
  profile: Profile; build: BuildReport; openId?: string; openAt?: number; onOpen: (id?: string, at?: number) => void; onChangeRule: (f: FileFamily) => void; onShowKind: (f: FileFamily) => void;
}) {
  const { run, pending } = useAction();
  const call = useCall();
  const go = useGo();
  const n = needsOf(b);
  const resolve = (c: Clash) => (r: ClashResolution, pick?: string) => void run((a) => a.resolveClash(p.id, c.id, r, pick));
  const items: Item[] = [];

  n.dropped.forEach((d) => items.push(droppedItem(p, d, pending, () => go.openMod(d.modId), () => void run((a) => a.acceptDropped(p.id, d.id)))));
  n.decide.forEach((c) => items.push({
    id: c.id, tone: 'warn', action: 'Decide',
    title: `${c.piece}: pick which mod wins`,
    detail: `${c.sides.map((s) => `${modName(p, s.modId)} ${s.value}`).join('; ')}. Bayle won't choose this for you.`,
    body: <PieceStack clash={c} build={b} profile={p} pending={pending} onResolve={resolve(c)} />,
  }));
  n.check.forEach((c) => items.push({
    id: c.id, tone: 'warn', action: 'Check',
    title: `${c.piece}: the game changed under your pick`,
    detail: c.rebase ? `The original value moved from ${c.rebase.wasVanilla} to ${c.rebase.nowVanilla}. Your pick still applies.` : 'A mod in it was updated. Your pick still applies.',
    body: <PieceStack clash={c} build={b} profile={p} pending={pending} onResolve={resolve(c)}
      footer={<div className="flex flex-wrap items-center gap-2 border-t border-line pt-2.5">
        <Button size="sm" variant="primary" icon={<Check />} disabled={pending} onClick={() => resolve(c)(c.resolution, c.pickedId)}>Keep my pick</Button>
        <span className="text-xs text-t3">or choose another above.</span>
      </div>} />,
  }));
  n.rules.forEach((r) => {
    const all = b.clashes.filter((c) => (c.family === r.family && c.reason === 'rule') || (r.coupled?.includes(c.family) && c.reason === 'coupled'));
    const pieces = r.metIds?.length ? all.filter((c) => r.metIds!.includes(c.id)) : all;
    items.push({
      id: r.id, tone: 'warn', action: 'Check',
      title: `Your ${FAMILY[r.family].label} rule settled ${plural(r.meetsNew!, 'new piece')}`,
      detail: `${modName(p, r.order[0])} wins, as the rule says. Usually fine; worth a glance.`,
      body: (
        <div className="flex flex-col gap-2.5">
          <ul className="m-0 list-none overflow-hidden rounded-sm border border-line p-0 text-ui">
            {pieces.map((c) => <li key={c.id} className="flex items-center gap-3 border-b border-line px-3 py-1.5 last:border-b-0"><span className="min-w-0 flex-1 truncate">{c.piece}</span><span className="text-xs text-t3">{modName(p, c.winnerId)} wins</span></li>)}
          </ul>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="primary" icon={<Check />} onClick={() => void call((a) => a.confirmRule(p.id, r.id), { title: 'OK, the rule stays as it is' })}>Looks right</Button>
            <Button size="sm" onClick={() => onChangeRule(r.family)}>Change the rule</Button>
            <LinkButton className="text-xs" onClick={() => onShowKind(r.family)}>See all {all.length} in {FAMILY[r.family].label}</LinkButton>
          </div>
        </div>
      ),
    });
  });

  if (!items.length) return null;
  // Once the open item is settled it leaves the list; the one that took its place opens, like the next message in an inbox.
  const current = items.some((it) => it.id === openId) ? openId : openId && openAt !== undefined ? items[Math.min(openAt, items.length - 1)]?.id : undefined;
  const counts = [n.dropped.length && `${n.dropped.length} left out`, n.decide.length && `${n.decide.length} to decide`, n.check.length + n.rules.length && `${n.check.length + n.rules.length} to check`].filter(Boolean).join(', ');
  return (
    <section aria-label="Needs you" className="flex flex-col gap-2">
      <h2 className="m-0 flex items-baseline gap-2 text-section font-semibold">Needs you <span className="text-ui font-normal text-t3">{counts}</span></h2>
      <ul className="m-0 list-none overflow-hidden rounded-lg border border-accent/40 bg-panel p-0">
        {items.map((it, i) => {
          const open = current === it.id;
          return (
            <li key={it.id} data-need={it.id} className={cn('border-b border-line last:border-b-0', open && 'bg-t1/2.5')}>
              <div className="flex items-start gap-3 px-4 py-2.5">
                {it.tone === 'bad' ? <CircleAlert className="mt-0.5 size-4 shrink-0 text-bad" /> : <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warn" />}
                <div className="min-w-0 flex-1">
                  <div className="text-body font-medium">{it.title}</div>
                  {it.detail && <div className="mt-0.5 text-xs text-t3">{it.detail}</div>}
                </div>
                <Button size="sm" variant={open ? 'ghost' : 'default'} aria-expanded={open} onClick={() => onOpen(open ? undefined : it.id, i)}>{open ? 'Close' : it.action}</Button>
              </div>
              {open && <div className="px-4 pb-3.5 pl-11 max-[560px]:pl-4">{it.body}</div>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function droppedItem(p: Profile, d: DroppedChange, pending: boolean, openMod: () => void, accept: () => void): Item {
  const mod = modName(p, d.modId);
  const { plain, code } = splitWhat(d.what);
  return {
    id: d.id, tone: 'bad', action: 'Fix',
    title: `${mod}'s ${plain.replace(/^its /, '')} won't be in your game`,
    detail: d.reason,
    body: (
      <div className="flex flex-col gap-2.5">
        {d.fix && <p className="m-0 text-ui">{d.fix}</p>}
        <p className="m-0 text-xs text-t4">{d.file}{code ? ` · ${code}` : ''}</p>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={openMod}>Open {mod}</Button>
          <Button size="sm" variant="ghost" disabled={pending} onClick={accept}>Play without it</Button>
        </div>
      </div>
    ),
  };
}
