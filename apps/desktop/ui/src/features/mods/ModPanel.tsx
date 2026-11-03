import { useMemo } from 'react';
import { useForm, type Resolver } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { Trash2 } from 'lucide-react';
import type { Mod } from '@/api';
import { Sheet, Tabs } from '@/components/bayle/overlay';
import { Button } from '@/components/ui/button';
import { useAction, useBuild, useModFiles } from '@/data/hooks';
import { FEATURES } from '@/lib/features';
import { ModThumb } from '@/components/bayle/mod-thumb';
import { useShortcuts } from '@/app/useShortcuts';
import { useMods, type PanelTab } from './controller';
import { modOptionsSchema, NO_NATIVE, pickOptions, type ModOptions } from './modOptions';
import { dllFile, thumbName } from './identity';
import { FilesTab } from './panel/FilesTab';
import { UpdateTab } from './panel/UpdateTab';
import { ClashesTab } from './panel/ClashesTab';
import { ConfigsTab } from './panel/ConfigsTab';
import { LoadingTab } from './panel/OptionsTab';

/* ------------------------------------------------------------------ the panel */

export interface ModPanelProps { mod: Mod | undefined; tab: PanelTab; onTab: (t: PanelTab) => void; onClose: () => void }

/** One mod's options, files and settings files. Option edits are staged until Save. */
export function ModPanel({ mod, tab, onTab, onClose }: ModPanelProps) {
  const c = useMods();
  const { run, pending } = useAction();
  const files = useModFiles(mod ? c.profile.id : undefined, mod?.id);
  const build = useBuild(mod ? c.profile.id : undefined);
  const clashCount = mod ? (build.data?.clashes.filter((x) => x.sides.some((s) => s.modId === mod.id)).length ?? 0) + (build.data?.dropped.filter((d) => d.modId === mod.id).length ?? 0) : 0;
  const original = mod ? pickOptions(mod) : undefined;
  const otherIds = mod ? c.profile.mods.filter((x) => x.id !== mod.id && x.kind === 'package').map((x) => x.packageId) : [];
  // Staged until Save. `values` resets the form whenever the saved mod changes.
  const form = useForm<ModOptions>({
    resolver: mod ? (zodResolver(modOptionsSchema(mod, otherIds)) as Resolver<ModOptions>) : undefined,
    values: original ? { ...original, native: mod?.kind === 'native' ? (original.native ?? NO_NATIVE) : original.native } : undefined,
    mode: 'onChange',
  });
  const { isDirty, isValid } = form.formState;

  const save = form.handleSubmit((draft) => {
    if (!mod || !isDirty) return;
    onClose();
    void run((a) => a.updateMod(c.profile.id, mod.id, draft));
  });
  // Ctrl+S saves while the panel is open, like the other editors.
  const keys = useMemo(() => ({ 'ctrl+s': () => void save() }), [save]);
  useShortcuts(keys, !!mod);

  return (
    <Sheet open={!!mod} onOpenChange={(o) => !o && onClose()} width={520}
      title={mod ? <span className="flex min-w-0 items-center gap-2.5"><ModThumb name={thumbName(mod, c.profile)} src={mod.thumbnail} size={28} /><span className="truncate">{mod.name}</span></span> : ''} subtitle={mod ? (mod.kind === 'package' ? `Package · ${mod.folder} · in the profile since ${mod.addedOn}` : `Native · ${dllFile(mod)} in ${mod.folder.replace(/[\\/][^\\/]*$/, '')} · in the profile since ${mod.addedOn}`) : undefined}
      footer={mod && <>
        <Button variant="ghost-danger" icon={<Trash2 />} className="mr-auto" onClick={() => { onClose(); c.askRemove([mod.id]); }}>Remove</Button>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!isDirty || !isValid || pending} title={!isDirty ? 'Change an option to enable Save' : !isValid ? 'Fix the highlighted option first' : 'Save (Ctrl+S)'} onClick={() => void save()}>Save</Button>
      </>}>
      {mod && (
        <div>
          <Tabs value={tab} onValueChange={(v) => onTab(v as PanelTab)} tabs={[
            { value: 'loading', label: 'Options', content: <LoadingTab mod={mod} form={form} /> },
            ...(FEATURES.modVersions && mod.update ? [{ value: 'update', label: `Update ${mod.update.version}`, content: <UpdateTab mod={mod} /> }] : []),
            ...(mod.kind === 'package' ? [{ value: 'clashes', label: 'Clashes', count: clashCount, content: <ClashesTab mod={mod} /> }] : []),
            { value: 'files', label: 'Files', count: files.data?.length, content: <FilesTab mod={mod} files={files.data} /> },
            { value: 'configs', label: 'Config files', count: mod.configs.length, content: <ConfigsTab mod={mod} /> },
          ]} />
        </div>
      )}
    </Sheet>
  );
}
