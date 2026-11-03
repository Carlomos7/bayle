import { useState } from 'react';
import { Bell } from 'lucide-react';
import { Button, LinkButton } from '@/components/ui/button';
import { SectionLabel } from '@/components/bayle/layout';
import { useDialogs } from '@/state/dialogs';
import { toast } from '@/state/toasts';
import { useCall } from '@/data/hooks';
import { LINKS } from '@/app/links';
import { cn } from '@/lib/utils';
import { useSettingsCtx } from '../context';
import { isChanged, type RowDef, type SectionDef } from '../schema';
import { SettingRow } from '../SettingRow';
import { AboutCard } from '../rowExtras';

/** Rows that share a group sit in one card, under a small uppercase label. */
function groupRows(rows: RowDef[]): { group?: string; rows: RowDef[] }[] {
  const out: { group?: string; rows: RowDef[] }[] = [];
  rows.forEach((r) => {
    const last = out[out.length - 1];
    if (last && last.group === r.group) last.rows.push(r);
    else out.push({ group: r.group, rows: [r] });
  });
  return out;
}

function UpdateBanner() {
  const { info } = useSettingsCtx();
  const show = useDialogs((s) => s.show);
  const call = useCall();
  const [skipped, setSkipped] = useState(false);
  if (!info?.update || skipped) return null;
  const version = info.update.version;
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-accent-ring bg-accent-soft py-3 pr-3.5 pl-4">
      <Bell className="size-[18px] text-accent" />
      <div className="flex flex-col gap-0.5"><b className="font-semibold">Bayle {info.update.version} is available</b><span className="text-ui text-t2">{info.update.channel === 'beta' ? 'Beta' : 'Stable'} channel · one click, then a restart. Your settings stay.</span></div>
      <span className="flex-1" />
      <Button size="sm" variant="ghost" onClick={() => void call((a) => a.openUrl(LINKS.releaseNotes(version)))}>Notes</Button>
      <Button size="sm" variant="ghost" onClick={() => { setSkipped(true); toast({ kind: 'info', title: `Skipped Bayle ${version}`, detail: 'You will be told about the next version.' }); }}>Skip</Button>
      <Button size="sm" variant="primary" onClick={() => show({ id: 'updates' })}>Update now</Button>
    </div>
  );
}

/** One section: header (with Reset section when something changed), then its cards. */
export function Section({ section, rows, searching }: { section: SectionDef; rows: RowDef[]; searching: boolean }) {
  const { settings, defaults, reset } = useSettingsCtx();
  const changed = rows.filter((r) => isChanged(r, settings, defaults));
  const isShortcuts = section.id === 'shortcuts';
  return (
    <section id={`set-${section.id}`} aria-labelledby={`set-${section.id}-h`} className="flex scroll-mt-5 flex-col gap-3">
      <header className="flex items-end gap-3">
        <div className="min-w-0 flex-1">
          <h2 id={`set-${section.id}-h`} className="m-0 font-serif text-heading leading-tight font-semibold">{section.title}</h2>
          <p className="mt-1 mb-0 text-ui text-t3">{section.description}</p>
        </div>
        {changed.length > 0 && <LinkButton className="text-xs whitespace-nowrap" onClick={() => reset(changed)}>Reset section</LinkButton>}
      </header>
      {section.id === 'updates' && !searching && <UpdateBanner />}
      {section.id === 'about'
        ? <AboutCard />
        : groupRows(rows).map((g, i) => (
          <div key={g.group ?? i} className={cn('rounded-lg border border-line2 bg-panel px-[18px]', isShortcuts && 'grid grid-cols-2 gap-x-8 pb-2.5 max-[980px]:grid-cols-1')}>
            {g.group && <SectionLabel className={cn('pt-3.5 pb-1', isShortcuts && 'col-span-full')}>{g.group}</SectionLabel>}
            {g.rows.map((r) => <SettingRow key={r.id} row={r} />)}
          </div>
        ))}
    </section>
  );
}
