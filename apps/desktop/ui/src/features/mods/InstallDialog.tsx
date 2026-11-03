import { useEffect, useRef, useState } from 'react';
import { FileArchive, FolderOpen } from 'lucide-react';
import type { InstallPreview } from '@/api';
import { useDialogs } from '@/state/dialogs';
import { useAction, useCall, useCurrent } from '@/data/hooks';
import { Dialog } from '@/components/bayle/overlay';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/bayle/controls';
import { Tag } from '@/components/bayle/badge';
import { OverhaulSheet } from '@/features/overhaul';
import { cn } from '@/lib/utils';

/**
 * Install a mod in two steps: pick the source, then review what Bayle found
 * (package, native, or one with a recipe) and which files go in.
 */
export function InstallDialog({ path }: { path?: string }) {
  const close = useDialogs((s) => s.close);
  const { profile } = useCurrent();
  const call = useCall();
  const { run } = useAction();
  const [preview, setPreview] = useState<InstallPreview | null>(null);
  const [loading, setLoading] = useState(false);
  /** Mods with a recipe open the plan instead of installing as is. */
  const [setupOpen, setSetupOpen] = useState(false);

  const pick = async (kind: 'file' | 'folder') => {
    const src = path ?? (await call((a) => (kind === 'file'
      ? a.pickFile({ title: 'Install a mod', filters: [{ name: 'Mods', extensions: ['zip', '7z', 'rar', 'dll'] }] })
      : a.pickFolder({ title: 'Install a mod folder' }))));
    if (!src) return;
    setLoading(true);
    const p = await call((a) => a.previewInstall({ path: src, profileId: profile?.id }));
    setLoading(false);
    if (p) setPreview(p);
  };

  // Opened with a path (e.g. "Add a folder that is not loaded"): read it straight away.
  const started = useRef(false);
  useEffect(() => {
    if (!path || started.current) return;
    started.current = true;
    setLoading(true);
    void call((a) => a.previewInstall({ path, profileId: profile?.id })).then((p) => { setLoading(false); if (p) setPreview(p); });
  }, [path, call, profile?.id]);

  const install = () => {
    if (!profile || !preview) return;
    if (preview.detectedAs === 'overhaul' && preview.setupId) { setSetupOpen(true); return; }
    close();
    void run((a) => a.install(profile.id, preview));
  };

  if (setupOpen && preview?.setupId && profile) {
    return <OverhaulSheet setupId={preview.setupId} profileId={profile.id} mode="install" open onOpenChange={(o) => { if (!o) close(); }} />;
  }

  return (
    <Dialog open onOpenChange={(o) => !o && close()} width={540}
      title={preview ? `Install ${preview.name}${preview.version ? ` ${preview.version}` : ''}` : 'Install mod'}
      description={preview ? `Into ${profile?.name}. Bayle found ${preview.detectedAs === 'native' ? 'a native (a DLL me3 injects)' : preview.detectedAs === 'overhaul' ? 'a recipe for it, so it is built on top of your other mods' : 'a package (game files me3 overlays)'}.` : 'From a .zip, .7z, .rar, a .dll or a folder. Bayle finds the mod inside, even below a wrapper folder.'}
      footer={preview
        ? <><Button variant="ghost" className="mr-auto" onClick={() => setPreview(null)}>Back</Button><Button variant="ghost" onClick={close}>Cancel</Button><Button variant="primary" onClick={install} disabled={!preview.items.some((i) => i.include)}>{preview.detectedAs === 'overhaul' ? 'Review the plan…' : 'Install'}</Button></>
        : <Button variant="ghost" onClick={close}>Cancel</Button>}>
      {!preview ? (
        <div className="grid grid-cols-2 gap-3">
          <button type="button" disabled={loading} onClick={() => void pick('file')} className="flex flex-col items-start gap-2 rounded-lg border border-line2 p-4 text-left hover:border-t4 hover:bg-hover">
            <FileArchive className="size-5 text-accent" /><b className="font-semibold">A file</b><span className="text-xs text-t3">.zip, .7z, .rar or .dll</span>
          </button>
          <button type="button" disabled={loading} onClick={() => void pick('folder')} className="flex flex-col items-start gap-2 rounded-lg border border-line2 p-4 text-left hover:border-t4 hover:bg-hover">
            <FolderOpen className="size-5 text-accent" /><b className="font-semibold">A folder</b><span className="text-xs text-t3">already unpacked</span>
          </button>
          {loading && <p className="col-span-2 m-0 text-xs text-t3">Reading the download…</p>}
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2 text-xs text-t3"><Tag tone={preview.detectedAs === 'overhaul' ? 'vio' : 'neutral'}>{preview.detectedAs === 'overhaul' ? 'has a recipe' : preview.detectedAs}</Tag><span className="truncate font-mono">{preview.source}</span></div>
          <ul className="m-0 list-none overflow-hidden rounded-lg border border-line2 p-0">
            {preview.items.map((it, i) => (
              <li key={it.path} className="flex items-center gap-3 border-b border-line px-3 py-2 last:border-b-0">
                <Checkbox checked={it.include} aria-label={`Include ${it.path}`}
                  onCheckedChange={(on) => setPreview({ ...preview, items: preview.items.map((x, j) => (j === i ? { ...x, include: on } : x)) })} />
                <span className={cn('flex-1 truncate font-mono text-ui', !it.include && 'text-t4 line-through')}>{it.path}</span>
                <span className="text-xs text-t3">{it.what}</span><span className="w-14 text-right text-xs text-t4 tabular-nums">{it.size}</span>
              </li>
            ))}
          </ul>
          {preview.warnings.map((w) => <p key={w} className="m-0 text-xs text-warn">{w}</p>)}
        </div>
      )}
    </Dialog>
  );
}
