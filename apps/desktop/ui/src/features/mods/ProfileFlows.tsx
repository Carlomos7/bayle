import { useState, type ReactNode } from 'react';
import { dllFile, dllLabel } from './identity';
import { ChevronDown, Copy, FolderInput, PenLine, Plus, Settings2, Trash2, Wrench } from 'lucide-react';
import type { Mod, Profile } from '@/api';
import { NameDialog } from '@/components/bayle/name-dialog';
import { Dialog, ConfirmDialog } from '@/components/bayle/overlay';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/bayle/controls';
import { Tag } from '@/components/bayle/badge';
import { DropdownMenu, item, sep, type MenuEntry } from '@/components/bayle/menu';
import { SectionLabel } from '@/components/bayle/layout';
import { useAction, useAttachable, useCall } from '@/data/hooks';
import { useDialogs } from '@/state/dialogs';
import { hasOverhaul } from './status';

/* ------------------------------------------------------------------ manage profile */

export function ManageProfileMenu({ profile, profileCount, onMoveIn, onTakeOver, onRemoveOverhaul }: { profile: Profile; profileCount: number; onMoveIn: () => void; onTakeOver: () => void; onRemoveOverhaul: () => void }) {
  const show = useDialogs((s) => s.show);
  const ovh = profile.mods.find((m) => m.staysLast);
  const items: MenuEntry[] = [
    item('Rename…', () => show({ id: 'renameProfile', profileId: profile.id }), { icon: <PenLine />, kbd: 'F2' }),
    item('Duplicate…', () => show({ id: 'newProfile', copyFrom: profile.id }), { icon: <Copy /> }),
    item('New profile…', () => show({ id: 'newProfile' }), { icon: <Plus />, kbd: 'Ctrl N' }),
    sep,
    item("Move into Bayle's folder…", onMoveIn, { icon: <FolderInput />, disabled: !profile.outsidePath, why: "Already in Bayle's folder" }),
    item(`Take over ${profile.installer?.name ?? 'an installer setup'}…`, onTakeOver, { icon: <Wrench />, disabled: !profile.installer, why: "No mod's own installer changed this profile" }),
    item(ovh ? `Remove ${ovh.name} and its merged files…` : 'Remove the last-loading mod…', onRemoveOverhaul, { icon: <Trash2 />, disabled: !ovh?.setupId, why: 'No mod in this profile loads last' }),
    sep,
    item('Delete profile…', () => show({ id: 'deleteProfile', profileId: profile.id }), { icon: <Trash2 />, danger: true, disabled: profileCount < 2, why: 'A game needs at least one profile' }),
  ];
  return (
    <DropdownMenu items={items} trigger={
      <Button size="sm" variant="ghost" className="-ml-2.5" icon={<Settings2 />}>Manage profile<ChevronDown className="size-3!" /></Button>
    } />
  );
}

/* ------------------------------------------------------------------ move in */

export function MoveInDialog({ profile, open, onOpenChange }: { profile: Profile; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { run } = useAction();
  const slug = profile.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const pk = profile.mods.filter((m) => m.kind === 'package' && !m.staysLast).map((m) => m.name);
  const na = profile.mods.filter((m) => m.kind === 'native').map((m) => m.name);
  const oh = profile.mods.find((m) => m.staysLast);
  const rows: [string, string][] = [
    [`${slug}.me3`, 'the profile'], ['packages\\', pk.join(', ') || 'none'], ['natives\\', na.join(', ') || 'none'],
    ...(oh ? [[`${oh.folder}\\`, `${oh.name}, kept together`] as [string, string]] : []),
    ['builds\\', "Bayle's merged copies"], ['.bayle\\', 'backups and records'],
  ];
  return (
    <Dialog open={open} onOpenChange={onOpenChange} width={520} title={`Move ${profile.name} into Bayle's folder?`} description={`From ${profile.outsidePath}. Only the mods this profile uses move.`}
      footer={<><Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button><Button variant="primary" onClick={() => { onOpenChange(false); void run((a) => a.moveProfileIn(profile.id)); }}>Move in</Button></>}>
      <div className="rounded-lg border border-line2 bg-bg p-3 font-mono text-xs leading-relaxed">
        <b className="font-semibold">b-eldenring\{slug}\</b>
        {rows.map(([p, w]) => <div key={p} className="flex gap-4 pl-4"><span className="w-28 shrink-0">{p}</span><i className="truncate text-t3 not-italic">{w}</i></div>)}
      </div>
      <SectionLabel className="mt-4 mb-1.5">Stay where they are</SectionLabel>
      <ul className="m-0 pl-4 text-ui text-t2">{(profile.strays ?? []).map((s) => <li key={s}><code>{s}</code> · not used by this profile</li>)}{!profile.strays?.length && <li>Nothing else</li>}</ul>
      <p className="mb-0 text-xs text-t3">Recorded in Activity with Undo, which moves everything back.</p>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ take over */

function List({ title, rows }: { title: string; rows: { title: string; detail: string; kept?: boolean }[] }) {
  return (
    <section className="mb-3">
      <SectionLabel className="mb-1.5">{title}</SectionLabel>
      <ul className="m-0 list-none divide-y divide-line overflow-hidden rounded-lg border border-line2 p-0">
        {rows.map((r) => (
          <li key={r.title} className="flex items-start gap-3 px-3 py-2">
            <div className="min-w-0 flex-1"><div className="text-ui font-medium">{r.title}</div><div className="text-xs text-t3">{r.detail}</div></div>
            {r.kept && <Tag tone="accent">kept</Tag>}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function TakeOverDialog({ profile, open, onOpenChange }: { profile: Profile; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { run } = useAction();
  const ins = profile.installer;
  if (!ins) return null;
  return (
    <Dialog open={open} onOpenChange={onOpenChange} width={560} title={`Take over ${ins.name}?`}
      description={`${ins.name}'s own installer changed ${profile.name}. Bayle undoes exactly those changes, so it can update, set up and undo it from now on.`}
      footer={<><Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button><Button variant="primary" onClick={() => { onOpenChange(false); void run((a) => a.takeOverInstaller(profile.id)); }}>Take over</Button></>}>
      <List title="What the installer added" rows={ins.entries} />
      <List title="Settings it changed" rows={ins.settings} />
      <List title="Leftovers Bayle removes" rows={ins.leftovers} />
      <p className="m-0 text-xs text-t3">Your other mods are not touched. Undo in Activity puts the installer's setup back exactly.</p>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ remove */

export function RemoveDialog({ profile, mods, onClose, onDone }: { profile: Profile; mods: Mod[]; onClose: () => void; onDone: () => void }) {
  const { run } = useAction();
  const merged = hasOverhaul(profile) && mods.some((m) => m.kind === 'package');
  const [rebuild, setRebuild] = useState(true);
  const one = mods.length === 1 ? mods[0] : undefined;
  return (
    <ConfirmDialog open onOpenChange={(o) => !o && onClose()} danger confirmLabel={one ? 'Remove' : `Remove ${mods.length}`}
      title={one ? `Remove ${dllLabel(one)} from the profile?` : `Remove ${mods.length} mods from ${profile.name}?`}
      description="Their folders go to the Recycle Bin. Restore in Activity puts them back where they were in the load order."
      onConfirm={() => { onDone(); void run((a) => a.removeMods(profile.id, mods.map((m) => m.id), { rebuild: merged && rebuild })); }}>
      <ul className="m-0 list-none divide-y divide-line overflow-hidden rounded-lg border border-line2 p-0">
        {mods.map((m) => <li key={m.id} className="flex items-center gap-3 px-3 py-2 text-ui"><b className="font-medium">{dllLabel(m)}</b><span className="truncate font-mono text-xs text-t3">{m.missing ? `${m.folder} · folder missing` : `${m.folder} · ${m.size}`}</span>{m.shared && <Tag tone="info">other profiles keep it</Tag>}</li>)}
      </ul>
      {merged && <label className="mt-3 flex items-center gap-2.5 text-ui"><Checkbox checked={rebuild} onCheckedChange={setRebuild} aria-label="Rebuild merged game data" />Rebuild the merged game data now</label>}
    </ConfirmDialog>
  );
}

/* ------------------------------------------------------------------ rename */

export function RenameModDialog({ profile, mod, onClose }: { profile: Profile; mod: Mod; onClose: () => void }) {
  const { run } = useAction();
  return (
    <NameDialog onOpenChange={(o) => !o && onClose()} title={`Rename ${dllLabel(mod)}`} description={mod.kind === 'native' ? `Only the name Bayle shows changes. The file (${dllFile(mod)}) and its folder stay the same.` : 'Only the name Bayle shows changes. The folder and package id stay the same.'}
      label="New name" initial={mod.name} submitLabel="Rename" rename taken={profile.mods.filter((m) => m.id !== mod.partOfModId && m.partOfModId !== mod.id).map((m) => m.name)} takenMessage="Another mod in this profile has that name."
      onSubmit={(name) => void run((a) => a.updateMod(profile.id, mod.id, { name }))} />
  );
}

/* ------------------------------------------------------------------ attach */

export function AttachDialog({ profile, mod, onClose }: { profile: Profile; mod: Mod; onClose: () => void }) {
  const found = useAttachable(profile.id, mod.id);
  const call = useCall();
  const { run } = useAction();
  const [extra, setExtra] = useState<string[]>([]);
  // Until the user ticks something, the first file found is ticked.
  const [touched, setTouched] = useState<Set<string> | null>(null);
  const picked = touched ?? new Set(found.data?.slice(0, 1) ?? []);
  const setPicked = (fn: (s: Set<string>) => Set<string>) => setTouched(fn(picked));
  const files = [...(found.data ?? []), ...extra];
  const toggle = (f: string, on: boolean) => setPicked((s) => { const n = new Set(s); if (on) n.add(f); else n.delete(f); return n; });
  const browse = async () => {
    const p = await call((a) => a.pickFile({ title: `Attach a settings file to ${mod.name}`, filters: [{ name: 'Settings', extensions: ['ini', 'toml', 'json', 'txt', 'cfg'] }] }));
    const n = p?.split(/[\\/]/).pop();
    if (n) { setExtra((x) => [...x, n]); toggle(n, true); }
  };
  const attach = () => { onClose(); void run((a) => a.attachConfig(profile.id, mod.id, [...picked])); };
  const rows: ReactNode = files.length
    ? files.map((f) => (
      <label key={f} className="flex h-10 items-center gap-2.5 px-3">
        <Checkbox checked={picked.has(f)} onCheckedChange={(on) => toggle(f, on)} aria-label={f} />
        <span className="flex-1 truncate font-mono text-ui">{f}</span><span className="text-xs text-t3">{extra.includes(f) ? 'picked' : 'beside the mod'}</span>
      </label>
    ))
    : <p className="m-0 px-3 py-4 text-center text-xs text-t3">{found.isLoading ? 'Looking beside the mod…' : 'No other settings files beside this mod. Browse for one below.'}</p>;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={`Attach a settings file to ${mod.name}`} description="Attached files show on Mod Configs, where you can edit them. The file stays where it is."
      footer={<><Button variant="ghost" className="mr-auto" onClick={() => void browse()}>Browse…</Button><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!picked.size} onClick={attach}>{picked.size > 1 ? `Attach ${picked.size} files` : 'Attach'}</Button></>}>
      <div className="divide-y divide-line overflow-hidden rounded-lg border border-line2">{rows}</div>
      {mod.configs.length > 0 && <p className="mb-0 text-xs text-t3">Already attached: {mod.configs.join(', ')}</p>}
    </Dialog>
  );
}
