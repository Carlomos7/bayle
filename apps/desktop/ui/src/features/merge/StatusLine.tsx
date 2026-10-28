import { Play } from 'lucide-react';
import type { BuildReport } from '@/api';
import { StatusChip } from '@/components/bayle/badge';
import { Button } from '@/components/ui/button';
import { useLaunch } from '@/app/useLaunch';
import { cn } from '@/lib/utils';
import { needsCount, needsRebuild } from './explain';

/* ------------------------------------------------------------------ status line */

/**
 * Where things stand, read only. Rebuilding lives in the dock at the bottom so
 * there is one place to do it. When nothing is left, this is the finish line,
 * with Launch. Never "ready": a build is not proof it works in game.
 */
export function StatusLine({ build: b }: { build: BuildReport }) {
  const { launch, disabled } = useLaunch();
  const rebuild = needsRebuild(b);
  const done = !rebuild && needsCount(b) === 0;
  return (
    <section aria-label="Merge status" className={cn('rounded-lg border bg-panel', done ? 'border-ok/40' : 'border-line2')}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
        <StatusChip tone={rebuild ? 'warn' : 'ok'}>{rebuild ? 'Rebuild needed' : done ? 'Nothing left to do here' : 'Built, nothing changed since'}</StatusChip>
        <span className="text-ui text-t3">{b.builtOn ? `Last built ${b.builtOn}, against ${b.baseline.game}` : 'Not built yet'}</span>
        {done && <Button size="sm" variant="primary" className="ml-auto" icon={<Play />} disabled={disabled} onClick={() => void launch()}>Launch</Button>}
      </div>
    </section>
  );
}
