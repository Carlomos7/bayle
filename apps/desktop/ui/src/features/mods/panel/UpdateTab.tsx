import { Download } from 'lucide-react';
import type { Mod } from '@/api';
import { Button } from '@/components/ui/button';
import { useAction } from '@/data/hooks';
import { FAMILY } from '@/features/merge/words';
import { cn } from '@/lib/utils';
import { useMods } from '../controller';

/* ------------------------------------------------------------------ Update tab */

/** A newer release, and what it would change before you take it. Updating is a mock action here. */
export function UpdateTab({ mod: m }: { mod: Mod }) {
  const u = m.update;
  const c = useMods();
  const { run } = useAction();
  if (!u) return <p className="m-0 rounded-lg border border-dashed border-line2 px-4 py-5 text-center text-ui text-t3">{m.name} is up to date.</p>;
  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-lg border border-line2 bg-panel px-4 py-3">
        <div className="text-body font-medium">{m.name} {u.version} is out <span className="font-normal text-t3">· {u.releasedOn} · you have {m.version}</span></div>
        {u.notes && <p className="m-0 mt-1 text-ui text-t2">{u.notes}</p>}
      </div>
      <ul className="m-0 list-none divide-y divide-line overflow-hidden rounded-lg border border-line2 p-0 text-ui">
        {u.changes.map((c) => <li key={c.family} className="flex items-center justify-between px-3 py-2"><span>{FAMILY[c.family].label}</span><span className="tabular-nums text-t3">{c.count.toLocaleString()} {c.unit} differ</span></li>)}
        <li className={cn('flex items-center justify-between px-3 py-2', u.touchesPicks && 'text-accent')}><span>Your picks</span><span className="tabular-nums">{u.touchesPicks ? `${u.touchesPicks} would need a look` : 'none affected'}</span></li>
        <li className={cn('flex items-center justify-between px-3 py-2', u.newClashes && 'text-warn')}><span>New clashes with your other mods</span><span className="tabular-nums">{u.newClashes || 'none'}</span></li>
      </ul>
      <p className="m-0 text-xs text-t3">Updating keeps your settings file and your picks. The old version stays for Undo, and the merge is rebuilt.</p>
      <div><Button size="sm" variant="primary" icon={<Download />} onClick={() => void run((a) => a.upgradeMod(c.profile.id, m.id))}>Update to {u.version}</Button></div>
    </div>
  );
}
