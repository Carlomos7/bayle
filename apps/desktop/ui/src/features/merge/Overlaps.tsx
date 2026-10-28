import { ChevronDown, ChevronRight, Link2 } from 'lucide-react';
import type { BuildReport, FileFamily, Profile } from '@/api';
import { Tag } from '@/components/bayle/badge';
import { Button } from '@/components/ui/button';
import { useAction } from '@/data/hooks';
import { cn } from '@/lib/utils';
import { kindOrder, modName, overlapKinds } from './explain';
import { PieceStack } from './PieceStack';
import { FAMILY } from './words';

export interface OverlapsProps {
  profile: Profile;
  build: BuildReport;
  /** Which kind row is open, and which piece in it. Owned by the page so Needs you and search can open them. */
  openKind?: FileFamily;
  openPiece?: string;
  onOpenKind: (f?: FileFamily) => void;
  onOpenPiece: (id?: string) => void;
  onChangeRule: (f: FileFamily) => void;
}

const SOURCE = { rule: 'by your rule', coupled: 'kept together by your rule', order: 'by load order' } as const;

/**
 * Where the mods overlap, one row per kind of file: who wins, why, and one
 * button to change it. Pieces sit one click down, each as a stack.
 */
export function Overlaps({ profile: p, build: b, openKind, openPiece, onOpenKind, onOpenPiece, onChangeRule }: OverlapsProps) {
  const { run, pending } = useAction();
  const kinds = overlapKinds(b);
  const fixed = b.choices === false;
  const involved = new Set(b.clashes.flatMap((c) => c.sides.map((s) => s.modId)));
  const others = p.mods.filter((m) => m.kind === 'package' && m.enabled && !m.missing && !involved.has(m.id)).length;

  return (
    <section aria-label="Where your mods overlap" className="flex flex-col gap-2">
      <h2 className="m-0 text-section font-semibold">Where your mods overlap</h2>
      {fixed && <p className="m-0 text-xs text-t3">Bayle merges in load order: the mod lower in the list wins. Choosing winners per file is coming.</p>}
      {(kinds.length > 0 || !fixed) && <div className="overflow-hidden rounded-lg border border-line2 bg-panel">
        {kinds.map((f) => {
          const k = kindOrder(p, b, f);
          const pieces = b.clashes.filter((c) => c.family === f);
          const singles = pieces.filter((c) => c.reason === 'pick' || c.reason === 'both').length;
          const coupledKinds = k.source === 'rule' ? (k.rule?.coupled ?? []).filter((x) => b.clashes.some((c) => c.family === x)) : [];
          const coupledPieces = b.clashes.filter((c) => coupledKinds.includes(c.family));
          const open = openKind === f;
          const fresh = k.source === 'rule' && k.rule?.meetsNew;
          return (
            <div key={f} data-kind={f} className="border-b border-line last:border-b-0">
              <div className="flex items-start gap-2 px-4 py-3">
                <button type="button" aria-expanded={open} onClick={() => { onOpenKind(open ? undefined : f); onOpenPiece(undefined); }}
                  className="-my-1 -ml-2 grid min-w-0 flex-1 grid-cols-[18px_100px_minmax(0,1fr)] items-start gap-x-2 rounded-sm px-2 py-1 text-left hover:bg-hover max-[720px]:grid-cols-[18px_minmax(0,1fr)]">
                  {open ? <ChevronDown className="mt-0.5 size-4 text-t3" /> : <ChevronRight className="mt-0.5 size-4 text-t3" />}
                  <span className="text-body font-semibold">{FAMILY[f].label}</span>
                  <span className="min-w-0 max-[720px]:col-start-2">
                    <span className="block text-body"><b className="font-semibold">{modName(p, k.order[0])}</b>{k.order.length > 1 && <span className="text-t3"> wins over {k.order.slice(1).map((id) => modName(p, id)).join(', ')}</span>}</span>
                    <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-t3">
                      <span>{SOURCE[k.source]}</span>
                      <span>· {pieces.length + coupledPieces.length} piece{pieces.length + coupledPieces.length === 1 ? '' : 's'}{singles ? `, ${singles} set one by one` : ''}</span>
                      {coupledKinds.map((x) => <span key={x} className="inline-flex items-center gap-1"><Link2 className="size-3" />{FAMILY[x].label.toLowerCase()} file kept with it</span>)}
                      {fresh ? <Tag tone="accent">settled {k.rule!.meetsNew} new piece{k.rule!.meetsNew === 1 ? '' : 's'}</Tag> : null}
                    </span>
                  </span>
                </button>
                {!fixed && <Button size="sm" onClick={() => onChangeRule(f)}>Change</Button>}
              </div>
              {open && (
                <ul className="m-0 list-none border-t border-line p-0">
                  {[...pieces, ...coupledPieces].map((c) => {
                    const shown = openPiece === c.id;
                    return (
                      <li key={c.id} data-piece={c.id} className="border-b border-line last:border-b-0">
                        <button type="button" aria-expanded={shown} onClick={() => onOpenPiece(shown ? undefined : c.id)}
                          className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-3 py-2 pr-4 pl-11 text-left max-[720px]:pl-4 max-[560px]:grid-cols-1 max-[560px]:gap-0.5 text-ui hover:bg-hover">
                          <span className="min-w-0 truncate">{c.piece}{c.family !== f && <span className="text-t4"> · {FAMILY[c.family].label.toLowerCase()}</span>}</span>
                          <span className={cn('text-xs whitespace-nowrap max-[560px]:whitespace-normal', c.reason === 'pick' || c.reason === 'both' ? 'text-accent' : 'text-t3')}>
                            {c.reason === 'both' ? 'both kept' : modName(p, c.winnerId)}{c.reason === 'pick' ? ' · your pick' : ''}{c.needsReview || c.unresolved ? ' · check' : ''}
                          </span>
                        </button>
                        {shown && <div className="pr-4 pb-3 pl-11 max-[720px]:pl-4"><PieceStack clash={c} build={b} profile={p} pending={pending} onResolve={(r, pick) => void run((a) => a.resolveClash(p.id, c.id, r, pick))} /></div>}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          );
        })}
      </div>}
      {others > 0 && <p className="m-0 text-xs text-t3">{others} other mod{others === 1 ? '' : 's'} {others === 1 ? "doesn't" : "don't"} overlap with anything, so {others === 1 ? 'it is' : 'they are'} used as {others === 1 ? 'it is' : 'they are'}.</p>}
    </section>
  );
}
