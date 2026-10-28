import { useState } from 'react';
import { FileText, Wrench } from 'lucide-react';
import type { ConfigFileRef } from '@/api';
import { SearchInput } from '@/components/bayle/controls';
import { Tag } from '@/components/bayle/badge';
import { cn } from '@/lib/utils';

interface Group { modId: string; modName: string; files: ConfigFileRef[] }

const group = (files: ConfigFileRef[]): Group[] => {
  const m = new Map<string, Group>();
  files.forEach((f) => {
    // A DLL's files sit under the mod it belongs to: launcher.txt from ersc.dll is a Seamless Co-op file.
    const key = f.groupId ?? f.modId;
    if (!m.has(key)) m.set(key, { modId: key, modName: f.modName, files: [] });
    m.get(key)!.files.push(f);
  });
  return [...m.values()];
};

/** Left column: every settings file in the profile, grouped under its mod. */
export function ConfigTree({ files, selected, dirtyId, onSelect }: { files: ConfigFileRef[]; selected?: string; dirtyId?: string; onSelect: (f: ConfigFileRef) => void }) {
  const [q, setQ] = useState('');
  const query = q.trim().toLowerCase();
  const groups = group(files)
    .map((g) => ({ ...g, files: g.modName.toLowerCase().includes(query) ? g.files : g.files.filter((f) => f.name.toLowerCase().includes(query)) }))
    .filter((g) => g.files.length);

  return (
    <nav aria-label="Settings files" className="flex flex-col gap-3">
      <SearchInput value={q} onChange={setQ} placeholder="Find a setting or file" aria-label="Find a setting or file" />
      <div className="flex flex-col gap-3">
        {groups.length === 0 && <p className="m-0 px-2 text-ui text-t3">No file matches “{q}”.</p>}
        {groups.map((g) => (
          <div key={g.modId}>
            <div className="truncate px-2 pb-1 text-ui font-semibold text-t1">{g.modName}</div>
            <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
              {g.files.map((f) => {
                const on = f.id === selected;
                return (
                  <li key={f.id}>
                    <button type="button" onClick={() => onSelect(f)} aria-current={on ? 'true' : undefined}
                      className={cn('relative flex h-8 w-full items-center gap-2 rounded-xs px-2 pl-4 text-left text-ui text-t2 hover:bg-hover hover:text-t1',
                        on && 'bg-accent-soft text-t1 before:absolute before:top-1.5 before:bottom-1.5 before:left-1 before:w-[2px] before:rounded-full before:bg-accent hover:bg-accent-soft')}>
                      {f.isSetup ? <Wrench className="size-3.5 shrink-0 text-vio" /> : <FileText className="size-3.5 shrink-0 text-t3" />}
                      <span className={cn('flex-1 truncate', !f.isSetup && 'font-mono')}>{f.name}</span>
                      {f.viaFile && <span className="shrink-0 font-mono text-micro text-t4" title={`Belongs to ${f.viaFile}`}>{f.viaFile}</span>}
                      {f.isSetup && <Tag tone="vio">Recipe</Tag>}
                      {f.id === dirtyId && <span className="size-1.5 shrink-0 rounded-full bg-accent" title="Unsaved changes" />}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </nav>
  );
}
