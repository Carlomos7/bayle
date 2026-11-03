import { FolderOpen } from 'lucide-react';
import type { ActivityEntry } from '@/api';
import { useCall, useLog, useSettings } from '@/data/hooks';
import { Sheet } from '@/components/bayle/overlay';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/** The whole log for one entry, in a side panel. */
export function LogSheet({ entry, onClose }: { entry: ActivityEntry | null; onClose: () => void }) {
  const log = useLog(entry?.id);
  const settings = useSettings();
  const call = useCall();
  return (
    <Sheet open={!!entry} onOpenChange={(o) => !o && onClose()} width={640} title={entry?.title ?? 'Log'} subtitle={entry ? `${entry.day} ${entry.time} · ${entry.duration}` : undefined}
      footer={<>
        <Button variant="ghost" icon={<FolderOpen />} className="mr-auto" onClick={() => settings.data && void call((a) => a.openPath(settings.data.paths.logs))}>Open logs folder</Button>
        <Button onClick={onClose}>Close</Button>
      </>}>
      <p className="mt-0 mb-2 text-xs text-t3">Only the end of a long file is shown; the logs folder has all of it.</p>
      <pre className="m-0 overflow-x-auto rounded-lg border border-line bg-bg px-3 py-2.5 font-mono text-xs leading-[1.7] whitespace-pre-wrap text-t2">
        {log.isLoading ? 'Reading the log…' : (log.data ?? []).map((l, i) => <span key={i} className={cn('block', /error/i.test(l) && 'text-bad')}>{l}</span>)}
      </pre>
      {entry && !entry.ok && <p className="mt-3 mb-0 text-ui text-bad">{entry.detail}</p>}
    </Sheet>
  );
}
