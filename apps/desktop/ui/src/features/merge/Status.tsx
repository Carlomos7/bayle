import { FileText, ListChecks, RefreshCw } from 'lucide-react';
import type { BuildReport, Profile } from '@/api';
import { Dialog, Sheet } from '@/components/bayle/overlay';
import { Button } from '@/components/ui/button';
import { useAction, useBuildPlan } from '@/data/hooks';

/** Second-level actions: the plan and the report. */
export function StatusTools({ onPlan, onReport }: { onPlan: () => void; onReport: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Button size="sm" variant="ghost" icon={<ListChecks />} onClick={onPlan}>What a rebuild would do</Button>
      <Button size="sm" variant="ghost" icon={<FileText />} onClick={onReport}>Full report</Button>
    </div>
  );
}

/** What a rebuild would do now. Reads only; nothing is written until Rebuild. */
export function PlanDialog({ profile, open, onOpenChange }: { profile: Profile; open: boolean; onOpenChange: (o: boolean) => void }) {
  const plan = useBuildPlan(open ? profile.id : undefined);
  const { run, pending } = useAction();
  return (
    <Dialog open={open} onOpenChange={onOpenChange} width={560} title="What a rebuild would do" description={plan.data ? `Read only: nothing is written until you press Rebuild, and the old build is kept for Undo.${plan.data.estimateSec ? ` About ${plan.data.estimateSec} s.` : ''}` : 'Working it out…'}
      footer={<><Button variant="ghost" onClick={() => onOpenChange(false)}>Close</Button><Button variant="primary" icon={<RefreshCw />} disabled={pending || !plan.data} onClick={() => { onOpenChange(false); void run((a) => a.rebuildMerged(profile.id)); }}>Rebuild now</Button></>}>
      {plan.data && (
        <ol className="m-0 flex list-none flex-col p-0">
          {plan.data.steps.map((s, i) => (
            <li key={i} className="grid grid-cols-[22px_1fr] gap-2 border-b border-line py-2 last:border-b-0">
              <span className="grid size-5 place-items-center rounded-full border border-line2 text-tag font-semibold text-t3">{i + 1}</span>
              <div><div className="text-body font-medium">{s.title}</div>{s.detail && <div className="mt-0.5 text-xs text-t3">{s.detail}</div>}</div>
            </li>
          ))}
        </ol>
      )}
    </Dialog>
  );
}

/** The merge report as the backend wrote it, for bug reports and the curious. */
export function ReportSheet({ build, open, onOpenChange }: { build: BuildReport; open: boolean; onOpenChange: (o: boolean) => void }) {
  const text = build.reportLines.join('\n');
  return (
    <Sheet open={open} onOpenChange={onOpenChange} width={640} title="Merge report" subtitle="Every file, what was merged, and who won each clash"
      footer={<Button className="ml-auto" onClick={() => void navigator.clipboard?.writeText(text)}>Copy</Button>}>
      {build.reportLines.length ? <pre className="m-0 rounded-lg border border-line bg-bg p-3 font-mono text-caption leading-[1.6] whitespace-pre-wrap text-t2">{text}</pre> : <p className="text-t3">No build yet, so no report.</p>}
    </Sheet>
  );
}
