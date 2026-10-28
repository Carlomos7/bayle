import { FileText, RefreshCw, Undo2 } from 'lucide-react';
import type { ActivityEntry, Game } from '@/api';
import { useAction, useCurrent, useLog } from '@/data/hooks';
import { useDialogs } from '@/state/dialogs';
import { Button } from '@/components/ui/button';
import { SectionLabel } from '@/components/bayle/layout';
import { cn } from '@/lib/utils';
import { canUndo } from './filter';

interface Props { entry: ActivityEntry; game?: Game; onUndo: (e: ActivityEntry) => void; onOpenLog: (e: ActivityEntry) => void }

/** What opens under an entry: the log and a fix for failures, what Undo does, or session details. */
export function EntryDetail({ entry, game, onUndo, onOpenLog }: Props) {
  const log = useLog(!entry.ok ? entry.id : undefined);
  const { profile } = useCurrent();
  const { run } = useAction();
  const show = useDialogs((s) => s.show);

  let body: React.ReactNode;
  if (!entry.ok) {
    body = (
      <>
        <div>
          <SectionLabel className="mb-2">What happened</SectionLabel>
          <pre className="m-0 overflow-x-auto rounded-lg border border-line bg-bg px-3 py-2.5 font-mono text-xs leading-[1.65] whitespace-pre-wrap text-t2">
            {log.isLoading ? 'Reading the log…' : (log.data ?? []).map((l, i) => <span key={i} className={cn('block', /error/i.test(l) && 'text-bad')}>{l}</span>)}
          </pre>
        </div>
        <div className="flex gap-2">
          <Button size="sm" icon={<FileText />} onClick={() => onOpenLog(entry)}>Open full log</Button>
          {entry.kind === 'rebuild' && profile && <Button size="sm" variant="primary" icon={<RefreshCw />} onClick={() => void run((a) => a.rebuildMerged(profile.id))}>Redo the rebuild</Button>}
          {entry.kind === 'install' && <Button size="sm" variant="primary" icon={<RefreshCw />} onClick={() => show({ id: 'install' })}>Try again</Button>}
        </div>
      </>
    );
  } else if (canUndo(entry)) {
    body = (
      <>
        <div>
          <SectionLabel className="mb-2">{entry.undoLabel ?? 'Undo'} will</SectionLabel>
          <ul className="m-0 flex flex-col gap-1 pl-[18px] text-ui text-t2">{(entry.undoLines ?? ['Put it back as it was']).map((l) => <li key={l}>{l}</li>)}</ul>
        </div>
        <div><Button size="sm" icon={<Undo2 />} onClick={() => onUndo(entry)}>{entry.undoLabel ?? 'Undo'}…</Button></div>
      </>
    );
  } else if (entry.kind === 'launch') {
    body = (
      <>
        <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-[18px] gap-y-1.5 text-ui">
          <dt className="text-t3">Game</dt><dd className="m-0">{game?.name ?? entry.gameId}</dd>
          <dt className="text-t3">Session</dt><dd className="m-0">{entry.duration}</dd>
          <dt className="text-t3">Afterwards</dt><dd className="m-0">{entry.detail.split(' · ').slice(1).join(' · ') || 'nothing to tidy'}</dd>
        </dl>
        {entry.hasLog && <div><Button size="sm" icon={<FileText />} onClick={() => onOpenLog(entry)}>Open log</Button></div>}
      </>
    );
  } else {
    body = <p className="m-0 text-ui text-t3">{entry.undone ? 'This was undone.' : (entry.noUndoReason ?? 'Nothing to undo for this one.')} Took {entry.duration}.</p>;
  }

  return <div className="flex flex-col gap-3 border-b border-line bg-[color-mix(in_srgb,var(--t1)_4%,var(--panel))] pt-1 pr-[18px] pb-4 pl-[62px]">{body}</div>;
}
