import { useEffect } from 'react';
import { ChevronDown, Layers, Power, PowerOff, Trash2, X } from 'lucide-react';
import type { Mod } from '@/api';
import { Button } from '@/components/ui/button';
import { DropdownMenu, header, item, type MenuEntry } from '@/components/bayle/menu';
import { plural } from '@/lib/utils';
import { useMods } from './controller';

export interface BulkBarProps {
  selected: Mod[];
  visibleCount: number;
  onSelectAll: () => void;
  onClear: () => void;
}

/** Floats bottom-centre over the content area while rows are ticked. */
export function BulkBar({ selected, visibleCount, onSelectAll, onClear }: BulkBarProps) {
  const c = useMods();
  const show = selected.length > 0;
  useEffect(() => {
    document.body.classList.toggle('has-bulk', show);
    return () => document.body.classList.remove('has-bulk');
  }, [show]);
  if (!show) return null;

  const ids = selected.map((m) => m.id);
  const pk = selected.filter((m) => m.kind === 'package').length;
  const na = selected.length - pk;
  const canOn = selected.some((m) => !m.enabled && !m.missing);
  const canOff = selected.some((m) => m.enabled);
  const addItems: MenuEntry[] = [
    header(`Add ${selected.length} to…`),
    ...c.otherProfiles.map((p) => item(p.name, () => c.addTo(p.id, ids), { icon: <Layers />, hint: `${p.modCount} mods now` })),
  ];

  return (
    <div role="toolbar" aria-label="Selected mods"
      className="fixed bottom-[22px] left-[calc(56px+(100vw-56px)/2)] z-20 flex max-w-[calc(100vw-80px)] -translate-x-1/2 items-center gap-0.5 rounded-lg border border-line2 bg-raise p-1.5 shadow-[0_18px_50px_rgb(0_0_0/.55),0_2px_6px_rgb(0_0_0/.3)] animate-[rise_.16s_ease-out] max-[820px]:left-1/2">
      <span className="flex items-center gap-2.5 pr-2 pl-1">
        <span className="grid h-[26px] min-w-[26px] place-items-center rounded-sm bg-accent-fill px-1.5 text-ui font-bold text-on-accent tabular-nums">{selected.length}</span>
        <span className="flex flex-col leading-tight">
          <b className="text-ui font-semibold">selected</b>
          <small className="text-caption whitespace-nowrap text-t3 max-[820px]:hidden">
            {[pk && plural(pk, 'package'), na && plural(na, 'native')].filter(Boolean).join(' · ')}
            {selected.length < visibleCount && <> · <button type="button" className="text-accent hover:underline" onClick={onSelectAll}>Select all {visibleCount}</button></>}
          </small>
        </span>
      </span>
      <span className="mx-1 h-[22px] w-px bg-line2" />
      <Button size="sm" variant="ghost" icon={<Power />} disabled={!canOn} title={canOn ? undefined : 'All of them are on already'} onClick={() => c.setEnabled(ids, true)}>Turn on</Button>
      <Button size="sm" variant="ghost" icon={<PowerOff />} disabled={!canOff} title={canOff ? undefined : 'All of them are off already'} onClick={() => c.setEnabled(ids, false)}>Turn off</Button>
      <DropdownMenu side="top" items={addItems} trigger={
        <Button size="sm" variant="ghost" icon={<Layers />} disabled={!c.otherProfiles.length} title={c.otherProfiles.length ? undefined : 'No other profile in this game'}>Add to profile<ChevronDown className="size-3!" /></Button>
      } />
      <Button size="sm" variant="ghost-danger" icon={<Trash2 />} onClick={() => c.askRemove(ids)}>Remove</Button>
      <span className="mx-1 h-[22px] w-px bg-line2" />
      <Button size="sm" variant="ghost" iconOnly icon={<X />} aria-label="Clear selection" title="Clear selection (Esc)" onClick={onClear} />
    </div>
  );
}
