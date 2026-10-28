import type { ReactNode } from 'react';
import { Box, Cpu, Download, Gamepad2, GitMerge, History, Layers, Moon, Play, RefreshCw, Save, Settings, SlidersHorizontal, Users } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { useUi } from '@/state/ui';
import { useDialogs } from '@/state/dialogs';
import { useCall, useCurrent, useGames, useProfiles } from '@/data/hooks';
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandShortcut } from '@/components/ui/command';
import { useLaunch } from '../useLaunch';
import { useGo, type PageId } from '../nav';

interface Cmd { label: string; hint?: string; icon: ReactNode; run: () => void; keywords?: string[] }

/** Ctrl+K: jump to any page, mod, profile, game or common action by typing (shadcn Command). */
export function CommandPalette() {
  const open = useUi((s) => s.commandOpen);
  const setOpen = useUi((s) => s.setCommandOpen);
  const setGame = useUi((s) => s.setGame);
  const show = useDialogs((s) => s.show);
  const go = useGo();
  const { game, profile } = useCurrent();
  const games = useGames();
  const profiles = useProfiles(game?.id ?? '');
  const call = useCall();
  const qc = useQueryClient();
  const { launch } = useLaunch();

  const page = (id: PageId, label: string, icon: ReactNode): Cmd => ({ label, icon, run: () => go.page(id) });
  const groups: [string, Cmd[]][] = [
    ['Actions', [
      { label: 'Launch', hint: profile?.name, icon: <Play />, run: () => void launch() },
      { label: 'Install mod…', icon: <Download />, run: () => show({ id: 'install' }) },
      { label: 'Rescan mods and saves', icon: <RefreshCw />, run: () => void qc.invalidateQueries() },
      { label: 'Rebuild merged game data', hint: profile?.name, icon: <GitMerge />, run: () => { if (profile) void call((a) => a.rebuildMerged(profile.id), { title: 'Merged game data rebuilt' }); }, keywords: ['merge', 'build', 'clash'] },
    ]],
    ['Pages', [page('mods', 'Mods', <Layers />), page('saves', 'Saves', <Save />), page('merge', 'Merge', <GitMerge />), page('configs', 'Mod Configs', <SlidersHorizontal />), page('activity', 'Activity', <History />), page('settings', 'Settings', <Settings />)]],
    [`Mods in ${profile?.name ?? 'this profile'}`, (profile?.mods ?? []).map((m) => ({ label: m.name, hint: m.kind === 'package' ? `Package · ${m.enabled ? 'on' : 'off'}` : `Native${m.file && m.file !== m.name ? ` · ${m.file}` : ''} · ${m.enabled ? 'on' : 'off'}`, keywords: [m.file, m.packageId].filter((x): x is string => !!x), icon: m.kind === 'package' ? <Box /> : <Cpu />, run: () => go.openMod(m.id) }))],
    ['Switch profile', (profiles.data ?? []).filter((p) => p.id !== profile?.id).map((p) => ({ label: p.name, hint: `${p.enabledCount} of ${p.modCount} mods on`, icon: <Users />, run: () => { if (game) void call((a) => a.setActiveProfile(game.id, p.id), { title: `Switched to ${p.name}` }); } }))],
    ['Switch game', (games.data ?? []).filter((g) => g.id !== game?.id).map((g) => ({ label: g.name, hint: g.supported ? undefined : 'not supported yet', icon: <Gamepad2 />, run: () => setGame(g.id) }))],
    ['Settings', [
      { label: 'Theme', icon: <Moon />, run: () => go.openSettings('appearance'), keywords: ['dark', 'light', 'bayle', 'appearance'] },
      { label: 'Rebuild merged mods before launch', icon: <Settings />, run: () => go.openSettings('launch') },
    ]],
  ];

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder="Search pages, mods, profiles, actions" aria-label="Search" />
      <CommandList>
        <CommandEmpty>Nothing matches.</CommandEmpty>
        {groups.filter(([, items]) => items.length).map(([heading, items]) => (
          <CommandGroup key={heading} heading={heading}>
            {items.map((c) => (
              <CommandItem key={`${heading}:${c.label}:${c.hint ?? ''}`} value={`${c.label} · ${c.hint ?? ''} · ${heading}`} keywords={c.keywords}
                onSelect={() => { setOpen(false); c.run(); }}>
                {c.icon}<span className="flex-1 truncate">{c.label}</span>{c.hint && <CommandShortcut>{c.hint}</CommandShortcut>}
              </CommandItem>
            ))}
          </CommandGroup>
        ))}
      </CommandList>
    </CommandDialog>
  );
}
