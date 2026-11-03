import { FileText, Link2 } from 'lucide-react';
import type { Mod } from '@/api';
import { Button } from '@/components/ui/button';
import { useAction } from '@/data/hooks';
import { useMods } from '../controller';

/* ------------------------------------------------------------------ Config files tab */

export function ConfigsTab({ mod: m }: { mod: Mod }) {
  const c = useMods();
  const { run } = useAction();
  return (
    <div className="flex flex-col gap-3">
      {m.configs.length ? (
        <ul className="m-0 list-none divide-y divide-line overflow-hidden rounded-lg border border-line2 p-0">
          {m.configs.map((f) => (
            <li key={f} className="flex h-11 items-center gap-2.5 px-3">
              <FileText className="size-3.5 shrink-0 text-t3" />
              <span className="flex-1 truncate font-mono text-ui">{f}</span>
              <Button size="sm" variant="ghost" onClick={() => c.openConfig(m, f)}>Open</Button>
              <Button size="sm" variant="ghost" title="Stop showing it on Mod Configs. The file stays where it is." onClick={() => void run((a) => a.detachConfig(c.profile.id, m.id, f))}>Detach</Button>
            </li>
          ))}
        </ul>
      ) : <p className="m-0 rounded-lg border border-dashed border-line2 px-4 py-5 text-center text-ui text-t3">No settings file attached. Attach one to edit it on Mod Configs.</p>}
      <div><Button size="sm" icon={<Link2 />} onClick={() => c.attach(m.id)}>Attach a file…</Button></div>
    </div>
  );
}
