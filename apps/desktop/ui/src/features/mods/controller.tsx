import { createContext, useContext } from 'react';
import { dllLabel } from './identity';
import { ArrowDown, ArrowUp, ChevronsDown, ChevronsUp, FileText, FolderOpen, Layers, Link2, PenLine, Pin, Power, PowerOff, Download, SlidersHorizontal, Trash2 } from 'lucide-react';
import type { Mod, Profile, ProfileSummary } from '@/api';
import { header, item, sep, sub, type MenuEntry } from '@/components/bayle/menu';
import { byKind } from './status';

export type PanelTab = 'loading' | 'update' | 'clashes' | 'files' | 'configs';

/** Everything a row, menu or bar can ask the Mods page to do. */
export interface ModsController {
  profile: Profile;
  otherProfiles: ProfileSummary[];
  openPanel: (id: string, tab?: PanelTab) => void;
  /** Go to Merge, filtered to one mod's clashes when given. */
  openMerge: (modId?: string) => void;
  setEnabled: (ids: string[], on: boolean) => void;
  move: (id: string, to: number | 'top' | 'bottom') => void;
  askRemove: (ids: string[]) => void;
  askRename: (id: string) => void;
  reinstall: (id: string) => void;
  addTo: (targetId: string, ids: string[]) => void;
  showInFolder: (m: Mod) => void;
  openConfig: (m: Mod, fileName: string) => void;
  attach: (id: string) => void;
}

export const ModsCtx = createContext<ModsController | null>(null);

export function useMods(): ModsController {
  const c = useContext(ModsCtx);
  if (!c) throw new Error('useMods must be used inside the Mods page');
  return c;
}

/** Right-click menu and the row's ⋯ menu: the same items in both places. */
export function modMenu(c: ModsController, m: Mod): MenuEntry[] {
  const list = byKind(c.profile, m.kind);
  const i = list.indexOf(m);
  const next = list[i + 1];
  const lockedNext = !!next?.staysLast;
  const lastMover = list.findIndex((x) => x.staysLast);
  const atBottom = i === list.length - 1 || (lastMover >= 0 && i === lastMover - 1);
  const moves: MenuEntry[] = m.staysLast
    ? [item('Move', () => {}, { icon: <Pin />, disabled: true, why: `${m.name} stays last: its rebuild tool merges the mods above it` })]
    : [
        item('Move up', () => c.move(m.id, -1), { icon: <ArrowUp />, kbd: 'Ctrl ↑', disabled: i === 0, why: 'Already first' }),
        item('Move down', () => c.move(m.id, 1), { icon: <ArrowDown />, kbd: 'Ctrl ↓', disabled: atBottom || lockedNext, why: lockedNext ? `${next?.name} stays last` : 'Already last' }),
        item('Move to top', () => c.move(m.id, 'top'), { icon: <ChevronsUp />, disabled: i === 0, why: 'Already first' }),
        item('Move to bottom', () => c.move(m.id, 'bottom'), { icon: <ChevronsDown />, disabled: atBottom, why: lastMover >= 0 ? `${list[lastMover]?.name} stays last` : 'Already last' }),
      ];
  return [
    header(dllLabel(m)),
    item('Options…', () => c.openPanel(m.id), { icon: <SlidersHorizontal />, kbd: 'Enter' }),
    m.missing
      ? item('Install again…', () => c.reinstall(m.id), { icon: <Download /> })
      : item(m.enabled ? 'Turn off' : 'Turn on', () => c.setEnabled([m.id], !m.enabled), { icon: m.enabled ? <PowerOff /> : <Power />, kbd: 'Space' }),
    sep,
    ...moves,
    sep,
    item('Rename…', () => c.askRename(m.id), { icon: <PenLine />, kbd: 'F2' }),
    sub('Config files', [
      ...m.configs.map((f) => item(f, () => c.openConfig(m, f), { icon: <FileText />, hint: 'open on Mod Configs' })),
      ...(m.configs.length ? [sep] : []),
      item('Attach a file…', () => c.attach(m.id), { icon: <Link2 /> }),
    ], { icon: <FileText /> }),
    sub('Add to profile', c.otherProfiles.map((p) => item(p.name, () => c.addTo(p.id, [m.id]), { icon: <Layers /> })), { icon: <Layers />, disabled: !c.otherProfiles.length, why: 'No other profile in this game' }),
    item('Show in folder', () => c.showInFolder(m), { icon: <FolderOpen />, disabled: !!m.missing, why: 'The folder is missing' }),
    sep,
    item('Remove from profile…', () => c.askRemove([m.id]), { icon: <Trash2 />, danger: true, kbd: 'Del' }),
  ];
}
