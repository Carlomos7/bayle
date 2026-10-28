import { Cpu, FolderOpen, Link2 } from 'lucide-react';
import type { Mod, ModFile } from '@/api';
import { Button, LinkButton } from '@/components/ui/button';
import { Tag } from '@/components/bayle/badge';
import { FileTree } from '@/components/bayle/file-tree';
import { useAction } from '@/data/hooks';
import { FEATURES } from '@/lib/features';
import { cn } from '@/lib/utils';
import { useMods } from '../controller';

/* ------------------------------------------------------------------ Files tab */

const DIRNOTE: Record<string, string> = { chr: 'animations', parts: 'models', sfx: 'effects', msg: 'text, one folder per language', menu: 'menu layout', map: 'map pieces', script: 'scripts', talk: 'dialogue', action: 'combat scripts', logs: 'written by the mod when it runs', m60: 'the Lands Between' };
const CONFIGABLE = /\.(ini|toml|json|txt|cfg|md)$/i;
const baseName = (p: string) => p.split('\\').pop() ?? p;

export function FilesTab({ mod: m, files }: { mod: Mod; files: ModFile[] | undefined }) {
  const c = useMods();
  const { run } = useAction();
  const dir = /\.dll$/i.test(m.folder) ? m.folder.replace(/\/[^/]+$/, '') : m.folder;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2 rounded-lg border border-line2 bg-panel py-1.5 pr-1.5 pl-3">
        <span className="flex min-w-0 items-center gap-2 font-mono text-xs"><FolderOpen className="size-3.5 shrink-0 text-accent" /><span className="truncate" title={dir}>{dir}</span></span>
        <span className="flex shrink-0 gap-1">
          <Button size="sm" variant="ghost" onClick={() => c.askRename(m.id)}>Rename</Button>
          <Button size="sm" icon={<FolderOpen />} disabled={!!m.missing} onClick={() => c.showInFolder(m)}>Open folder</Button>
        </span>
      </div>
      <dl className="m-0 grid grid-cols-[auto_1fr_auto_1fr] gap-x-4 gap-y-1.5 px-0.5 text-ui">
        <dt className="text-t3">Size</dt><dd className="m-0">{m.missing ? 'folder missing' : m.size}</dd>
        <dt className="text-t3">Files</dt><dd className="m-0 tabular-nums">{files?.length.toLocaleString() ?? '…'}</dd>
        {FEATURES.modVersions && <><dt className="text-t3">Version</dt><dd className="m-0">{m.version ?? 'none found'}</dd></>}
        <dt className="text-t3">Shared</dt><dd className="m-0">{m.shared ? 'Yes · used by other profiles' : 'No · its own copy'}</dd>
      </dl>
      {files === undefined ? <p className="text-xs text-t3">Reading the folder…</p> : (
        <FileTree
          key={m.id}
          files={files}
          isNotable={(f) => !!f.main || f.clash?.tone === 'warn'}
          emptyText={m.missing ? <>The folder {m.folder} is not there. <LinkButton onClick={() => c.reinstall(m.id)}>Install again</LinkButton></> : 'This folder is empty.'}
          fileIcon={(f) => (f.main ? <Cpu className="size-3.5 shrink-0 text-accent" /> : undefined)}
          renderDir={(inside, name) => {
            const warn = inside.filter((f) => f.clash?.tone === 'warn').length;
            const win = inside.filter((f) => f.clash?.tone === 'ok').length;
            return <span className="shrink-0 text-caption text-t3">{warn ? <Tag tone="warn">{warn} overridden</Tag> : win ? <Tag tone="ok">{win} win{win === 1 ? 's' : ''} a clash</Tag> : DIRNOTE[name] ?? ''}</span>;
          }}
          renderFile={(f) => {
            const name = baseName(f.path);
            if (f.clash) return <Tag tone={f.clash.tone}>{f.clash.note}</Tag>;
            if (m.configs.includes(name)) return <span className="flex shrink-0 items-center gap-2"><Tag tone="accent"><Link2 className="size-2.5" />Attached</Tag><LinkButton className="text-caption" onClick={() => c.openConfig(m, name)}>Open</LinkButton></span>;
            if (!f.main && CONFIGABLE.test(name) && !f.path.startsWith('logs\\')) {
              return <span className="flex min-w-0 shrink-0 items-center gap-2 text-caption text-t3"><span className="truncate">{f.what}</span>
                <LinkButton className="text-caption" title="Show it on Mod Configs so you can edit it there" onClick={() => void run((a) => a.attachConfig(c.profile.id, m.id, [name]))}>Attach</LinkButton></span>;
            }
            return <span className={cn('max-w-[220px] shrink-0 truncate text-caption text-t3', f.main && 'text-accent')}>{f.what}</span>;
          }}
        />
      )}
    </div>
  );
}
