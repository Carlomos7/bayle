import { useEffect, useState } from 'react';
import { Wrench } from 'lucide-react';
import type { ConfigFileRef } from '@/api';
import { useAction, useConfigFile, useConfigFiles, useCurrent } from '@/data/hooks';
import { useSearchRequest } from '@/app/nav';
import { toast } from '@/state/toasts';
import { EmptyState, Page, PageHeader } from '@/components/bayle/layout';
import { Dialog } from '@/components/bayle/overlay';
import { Button, LinkButton } from '@/components/ui/button';
import { DropdownMenu, header, item, type MenuEntry } from '@/components/bayle/menu';
import { useDialogs } from '@/state/dialogs';
import { OverhaulSheet } from '@/features/overhaul';
import { ConfigTree } from './ConfigTree';
import { ConfigEditor } from './ConfigEditor';
import { useConfigDraft } from './useConfigDraft';

/**
 * Mod Configs: every settings file in the profile, edited the same way.
 * Changes stay a draft until Save; leaving a file with a draft asks first.
 */
export function ConfigsPage() {
  const { game, profile } = useCurrent();
  const files = useConfigFiles(profile?.id);
  const showDialog = useDialogs((s) => s.show);
  const [chosen, setChosen] = useState<string | undefined>();
  const [pending, setPending] = useState<ConfigFileRef | null>(null);
  const [overhaul, setOverhaul] = useState<string | null>(null);
  // /configs?file=<id> (palette, Mods) selects a file; "setup:<id>" opens that overhaul setup.
  useSearchRequest('/configs', 'file', (id) => { if (id.startsWith('setup:')) setOverhaul(id.slice(6)); else setChosen(id); });
  const list = files.data ?? [];
  // Keep a valid selection: the chosen file if it still exists, else the first plain file.
  const selected = chosen && list.some((f) => f.id === chosen) ? chosen : list.find((f) => !f.isSetup)?.id;
  const setSelected = setChosen;
  const file = useConfigFile(profile?.id, selected);
  const draft = useConfigDraft(file.data);
  const { run, pending: saving } = useAction();

  const plain = list.filter((f) => !f.isSetup);
  const modCount = new Set(plain.map((f) => f.modId)).size;

  const save = async () => {
    if (!draft.valid) { toast({ kind: 'warn', title: 'Fix the highlighted values first', detail: 'Nothing was saved.' }); return; }
    const change = draft.change();
    if (!profile || !selected || !change) return;
    await run((a) => a.saveConfigFile(profile.id, selected, change));
  };

  // Ctrl+S saves the open file.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        if (draft.count) void save();
        else toast({ kind: 'info', title: 'Nothing to save' });
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const pick = (f: ConfigFileRef) => {
    if (f.isSetup) { setOverhaul(f.id.replace(/^setup:/, '')); return; }
    if (f.id === selected) return;
    if (draft.count) setPending(f); else setSelected(f.id);
  };

  const overhaulItems: MenuEntry[] = [
    header('Pick the mod'),
    ...(profile?.mods ?? []).filter((m) => m.kind === 'package').map((m): MenuEntry => item(m.name, () => (m.setupId ? setOverhaul(m.setupId) : showDialog({ id: 'install' })), {
      hint: m.setupId ? 'has a recipe' : 'install it again to write one',
      icon: <Wrench />,
    })),
  ];

  if (!profile) return <Page><PageHeader eyebrow={`Mod Configs · ${game?.name ?? ''}`} title="Loading…" /></Page>;

  return (
    <Page>
      <PageHeader
        eyebrow={<>Mod Configs <span aria-hidden>·</span> {game?.name}</>}
        title={profile.name}
        subtitle={`${modCount} ${modCount === 1 ? 'mod has' : 'mods have'} settings files. Nothing is written until you press Save (Ctrl+S).`}
        actions={<DropdownMenu align="end" items={overhaulItems} trigger={<LinkButton className="flex items-center gap-1.5 text-ui"><Wrench className="size-3.5" />Write a recipe for a mod…</LinkButton>} />}
      />
      {files.isSuccess && list.length === 0 ? (
        <EmptyState title="Nothing to configure yet">Some mods come with a settings file (an .ini or .toml). When one does, it shows up here as a form, so you never edit the file by hand. Nothing to do until then.</EmptyState>
      ) : (
        <div className="grid grid-cols-[280px_minmax(0,1fr)] gap-7 max-[1000px]:grid-cols-[240px_minmax(0,1fr)] max-[880px]:grid-cols-1">
          <aside className="sticky top-4 self-start max-[760px]:static"><ConfigTree files={list} selected={selected} dirtyId={draft.count ? selected : undefined} onSelect={pick} /></aside>
          <div className="min-w-0">
            {file.data ? <ConfigEditor key={file.data.id} profileId={profile.id} file={file.data} draft={draft} onSave={() => void save()} saving={saving} />
              : <p className="text-t3">{file.isLoading ? 'Opening…' : 'Pick a file on the left.'}</p>}
          </div>
        </div>
      )}

      <Dialog open={!!pending} onOpenChange={(o) => !o && setPending(null)} title={`Save your changes to ${file.data?.name ?? 'this file'}?`}
        description={`${draft.count} change${draft.count === 1 ? '' : 's'} are not saved yet. Opening ${pending?.name} without saving drops them.`}
        footer={<>
          <Button variant="ghost" className="mr-auto" onClick={() => setPending(null)}>Cancel</Button>
          <Button variant="ghost-danger" onClick={() => { draft.discard(); setSelected(pending?.id); setPending(null); }}>Discard</Button>
          <Button variant="primary" onClick={() => void save().then(() => { setSelected(pending?.id); setPending(null); })}>Save</Button>
        </>} />

      {overhaul && <OverhaulSheet setupId={overhaul} profileId={profile.id} mode="edit" open onOpenChange={(o) => !o && setOverhaul(null)} />}
    </Page>
  );
}
