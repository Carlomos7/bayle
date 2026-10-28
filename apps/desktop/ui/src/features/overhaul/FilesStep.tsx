import { TriangleAlert } from 'lucide-react';
import type { FileAction } from '@/api';
import { FileTree } from '@/components/bayle/file-tree';
import { Input, Select } from '@/components/bayle/controls';
import { Tag } from '@/components/bayle/badge';
import { toast } from '@/state/toasts';
import { ACTION_LABEL, ACTION_SHORT, PICKABLE, countByAction, type Draft, type DraftFile } from './actions';
import { cn } from '@/lib/utils';

const selectCls = 'h-7 w-[232px] text-code';

/** Step 1: which files go in, and what Bayle does with each one. */
export function FilesStep({ draft, onChange }: { draft: Draft; onChange: (d: Draft) => void }) {
  const update = (targets: DraftFile[], fn: (f: DraftFile) => DraftFile) => {
    const set = new Set(targets.map((t) => t.path));
    onChange({ ...draft, files: draft.files.map((f) => (set.has(f.path) ? fn(f) : f)) });
  };

  const include = (targets: DraftFile[], on: boolean) => {
    update(targets, (f) => {
      if (on) return f.action === 'leave' ? { ...f, action: f.before && f.before !== 'leave' ? f.before : 'copy' } : f;
      return f.action === 'leave' ? f : { ...f, before: f.action, action: 'leave' };
    });
    const needed = targets.filter((t) => t.needed && t.action !== 'leave');
    if (!on && needed.length) {
      toast({ kind: 'warn', title: `${needed.map((n) => n.path.split('\\').pop()).join(', ')} ${needed.length > 1 ? 'are' : 'is'} needed`,
        detail: `${draft.name} will likely not work without ${needed.length > 1 ? 'them' : 'it'}. Tick ${needed.length > 1 ? 'them' : 'it'} again to fix.` });
    }
  };

  const setAction = (targets: DraftFile[], a: FileAction) => update(targets, (f) => (f.action === 'leave' ? f : { ...f, action: a, before: a }));
  const missingNeeded = draft.files.filter((f) => f.needed && f.action === 'leave');
  const counts = countByAction(draft.files);

  return (
    <div className="flex flex-col gap-3">
      <p className="m-0 text-ui text-t3">
        The recipe, file by file. Most people never need this: change it only when {draft.name}'s readme says a file should be handled differently, or when the recipe got something wrong.
        Tick what goes into the game and pick what Bayle does with it. Folders set every file inside at once. Pinned files are ones {draft.name} needs.
      </p>
      <div className="flex flex-wrap gap-1.5" aria-label="Summary">
        {counts.map(([a, n]) => <Tag key={a}>{n.toLocaleString()} {ACTION_SHORT[a]}</Tag>)}
      </div>
      {missingNeeded.length > 0 && (
        <div role="alert" className="flex items-center gap-2 rounded-lg border border-warn/35 bg-warn-bg px-3 py-2 text-ui">
          <TriangleAlert className="size-4 shrink-0 text-warn" />
          <span>{missingNeeded.length} needed file{missingNeeded.length === 1 ? ' is' : 's are'} left out. {draft.name} will likely not work.</span>
        </div>
      )}
      <FileTree
        files={draft.files}
        maxHeight={520}
        isNotable={(f) => !!f.needed || f.action === 'place'}
        isNeeded={(f) => !!f.needed}
        selection={{ isIncluded: (f) => f.action !== 'leave', onChange: include }}
        renderDir={(inside, _name, open) => {
          const inc = inside.filter((f) => f.action !== 'leave');
          const acts = [...new Set(inc.map((f) => f.action))];
          if (!inc.length) return <span className="w-[232px] text-right text-xs text-t4">Left out</span>;
          return (
            <span className="flex items-center gap-2">
              {!open && <span className="text-caption whitespace-nowrap text-t3">{acts.length === 1 ? ACTION_SHORT[acts[0]!] : 'mixed'}</span>}
              <Select className={selectCls} aria-label="What Bayle does with everything in this folder" value={acts.length === 1 ? acts[0] : ''}
                onChange={(e) => setAction(inside, e.target.value as FileAction)}>
                {acts.length > 1 && <option value="" disabled>Mixed: each file keeps its own</option>}
                {PICKABLE.map((a) => <option key={a} value={a}>{ACTION_LABEL[a]}</option>)}
              </Select>
            </span>
          );
        }}
        renderFile={(f) => (
          <span className="flex items-center gap-2">
            <span className="max-w-[150px] truncate text-caption text-t3 max-[900px]:hidden">{f.what}</span>
            {f.action === 'leave' ? (
              <span className={cn('w-[232px] text-right text-xs', f.needed ? 'text-bad' : 'text-t4')}>{f.needed ? 'Left out · needed' : 'Left out'}</span>
            ) : (
              <span className="flex flex-col items-end gap-1">
                <Select className={selectCls} aria-label={`What Bayle does with ${f.path}`} value={f.action} onChange={(e) => setAction([f], e.target.value as FileAction)}>
                  {PICKABLE.map((a) => <option key={a} value={a}>{ACTION_LABEL[a]}</option>)}
                </Select>
                {f.action === 'place' && (
                  <Input className="h-7 w-[232px] font-mono text-caption" value={f.target ?? ''} placeholder="path inside the game files" aria-label="Where it goes"
                    onChange={(e) => update([f], (x) => ({ ...x, target: e.target.value }))} />
                )}
              </span>
            )}
          </span>
        )}
      />
    </div>
  );
}
