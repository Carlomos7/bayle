import { useMemo, useState, type ReactNode } from 'react';
import { ChevronRight, FileText, Folder, Pin } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Checkbox, SearchInput } from './controls';
import { Button } from '@/components/ui/button';

/**
 * A collapsible folder tree for any list of files with backslash paths.
 * Read-only by default; pass `selection` to get tick boxes on files and
 * folders (folders show a dash when partly included).
 */
export interface TreeFile { path: string }

interface Dir<F> { name: string; path: string; dirs: Map<string, Dir<F>>; files: { file: F; name: string }[] }

function build<F extends TreeFile>(files: F[]): Dir<F> {
  const root: Dir<F> = { name: '', path: '', dirs: new Map(), files: [] };
  files.forEach((file) => {
    const parts = file.path.split('\\');
    let n = root;
    parts.slice(0, -1).forEach((seg) => {
      if (!n.dirs.has(seg)) n.dirs.set(seg, { name: seg, path: `${n.path}${seg}\\`, dirs: new Map(), files: [] });
      n = n.dirs.get(seg)!;
    });
    n.files.push({ file, name: parts[parts.length - 1] ?? file.path });
  });
  return root;
}
const allFiles = <F,>(d: Dir<F>): F[] => [...d.files.map((x) => x.file), ...[...d.dirs.values()].flatMap(allFiles)];
const collator = new Intl.Collator(undefined, { numeric: true });

export interface FileTreeProps<F extends TreeFile> {
  files: F[];
  /** Folders open at first. Default: a single top folder, plus folders holding `isNotable` files when small. */
  isNotable?: (f: F) => boolean;
  /** Right-hand cells for a file row. */
  renderFile: (f: F) => ReactNode;
  /** Right-hand cells for a folder row (gets every file inside). */
  renderDir?: (files: F[], name: string, open: boolean) => ReactNode;
  /** Icon/emphasis for a file, e.g. the DLL of a native. */
  fileIcon?: (f: F) => ReactNode;
  /** Sort files in a folder; default puts notable first, then natural order. */
  selection?: { isIncluded: (f: F) => boolean; onChange: (files: F[], include: boolean) => void };
  /** Pin icon on files the user should not drop. */
  isNeeded?: (f: F) => boolean;
  emptyText?: ReactNode;
  className?: string;
  /** Height of the scroll area. */
  maxHeight?: number;
}

const PAGE = 25;

export function FileTree<F extends TreeFile>({ files, isNotable, renderFile, renderDir, fileIcon, selection, isNeeded, emptyText = 'This folder is empty.', className, maxHeight }: FileTreeProps<F>) {
  const root = useMemo(() => build(files), [files]);
  const [q, setQ] = useState('');
  const [more, setMore] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<Set<string>>(() => {
    const s = new Set<string>();
    if (root.dirs.size === 1 && !root.files.length) s.add([...root.dirs.values()][0]!.path);
    if (isNotable) {
      files.filter(isNotable).forEach((f) => {
        let acc = '';
        f.path.split('\\').slice(0, -1).forEach((seg, i) => {
          acc += `${seg}\\`;
          const size = files.filter((x) => x.path.startsWith(acc) && !x.path.slice(acc.length).includes('\\')).length;
          if (i === 0 || size <= 60) s.add(acc);
        });
      });
    }
    return s;
  });
  const query = q.trim().toLowerCase();
  const toggle = (p: string) => setOpen((s) => { const n = new Set(s); if (n.has(p)) n.delete(p); else n.add(p); return n; });
  const expandAll = () => { const s = new Set<string>(); files.forEach((f) => { let acc = ''; f.path.split('\\').slice(0, -1).forEach((seg) => { acc += `${seg}\\`; s.add(acc); }); }); setOpen(s); };

  if (!files.length) return <div className="rounded-lg border border-dashed border-line2 px-4 py-6 text-center text-ui text-t3">{emptyText}</div>;

  const rows: ReactNode[] = [];
  const indent = (d: number) => ({ paddingLeft: 6 + d * 16 });
  const walk = (n: Dir<F>, depth: number) => {
    [...n.dirs.values()].sort((a, b) => collator.compare(a.name, b.name)).forEach((d) => {
      const inside = allFiles(d);
      if (query && !inside.some((f) => f.path.toLowerCase().includes(query))) return;
      const isOpen = query ? true : open.has(d.path);
      const inc = selection ? inside.filter(selection.isIncluded).length : 0;
      const state = !selection ? false : inc === inside.length ? true : inc ? 'indeterminate' : false;
      rows.push(
        <div key={`d:${d.path}`} role="listitem" data-depth={depth}
          className="flex min-h-[34px] items-center gap-2 border-b border-line pr-3 hover:bg-hover" style={indent(depth)}>
          <button type="button" onClick={() => toggle(d.path)} aria-expanded={isOpen} aria-label={`${d.name} folder, ${inside.length} file${inside.length === 1 ? '' : 's'}`} className="grid size-[18px] place-items-center rounded-xs text-t3 hover:bg-press hover:text-t1">
            <ChevronRight className={cn('size-3 transition-transform', isOpen && 'rotate-90')} />
          </button>
          {selection && <Checkbox checked={state} onCheckedChange={(on) => selection.onChange(inside, on)} aria-label={`Include ${d.name}`} />}
          <span className="flex min-w-0 flex-1 items-center gap-2">
            <Folder className="size-3.5 shrink-0 text-accent" />
            <b className="truncate text-ui font-semibold">{d.name}\</b>
            {isNeeded && inside.some(isNeeded) && <Pin className="size-3 shrink-0 text-accent" aria-label="Holds needed files" />}
            <small className="text-caption whitespace-nowrap text-t3">{inside.length.toLocaleString()} file{inside.length === 1 ? '' : 's'}</small>
          </span>
          {renderDir?.(inside, d.name, isOpen)}
        </div>,
      );
      if (isOpen) walk(d, depth + 1);
    });
    const shown = n.files.filter((x) => !query || x.file.path.toLowerCase().includes(query))
      .sort((a, b) => Number(!!isNotable?.(b.file)) - Number(!!isNotable?.(a.file)) || collator.compare(a.name, b.name));
    const limit = query || more.has(n.path) ? Infinity : PAGE;
    shown.slice(0, limit).forEach(({ file, name }) => {
      const inc = selection ? selection.isIncluded(file) : true;
      rows.push(
        <div key={`f:${file.path}`} role="listitem" data-depth={depth}
          className="flex min-h-[34px] items-center gap-2 border-b border-line pr-3 hover:bg-hover" style={indent(depth)}>
          <span className="size-[18px] shrink-0" />
          {selection && <Checkbox checked={inc} onCheckedChange={(on) => selection.onChange([file], on)} aria-label={`Include ${name}`} />}
          <span className="flex min-w-0 flex-1 items-center gap-2">
            {fileIcon?.(file) ?? <FileText className="size-3.5 shrink-0 text-t3" />}
            <b title={file.path} className={cn('truncate font-mono text-ui font-medium', !inc && 'text-t4 line-through')}>{name}</b>
            {isNeeded?.(file) && <Pin className="size-3 shrink-0 text-accent" aria-label="Needed" />}
          </span>
          {renderFile(file)}
        </div>,
      );
    });
    if (shown.length > limit) {
      rows.push(
        <div key={`m:${n.path}`} className="flex min-h-[34px] items-center border-b border-line" style={indent(depth + 1)}>
          <button type="button" className="text-xs text-accent hover:underline" onClick={() => setMore((s) => new Set(s).add(n.path))}>
            Show {(shown.length - PAGE).toLocaleString()} more in {n.name || 'this folder'}\
          </button>
        </div>,
      );
    }
  };
  walk(root, 0);

  return (
    <div className={className}>
      <div className="mb-2 flex items-center gap-1.5">
        <SearchInput value={q} onChange={setQ} placeholder="Find a file" aria-label="Find a file" className="flex-1" />
        <Button size="sm" variant="ghost" onClick={expandAll}>Expand all</Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(new Set())}>Collapse all</Button>
      </div>
      {/* A flat list with disclosure buttons: an ARIA tree would promise arrow-key navigation this doesn't have. */}
      <div role="list" aria-label="Files" className="overflow-auto rounded-lg border border-line2 bg-panel [&>div:last-child]:border-b-0" style={maxHeight ? { maxHeight } : undefined}>
        {rows.length ? rows : <div className="px-4 py-5 text-center text-ui text-t3">No file matches “{q}”.</div>}
      </div>
    </div>
  );
}
