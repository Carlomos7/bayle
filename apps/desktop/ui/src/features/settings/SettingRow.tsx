import { type ReactNode } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { CheckCircle2 } from 'lucide-react';
import type { ThemeName } from '@/api';
import { useCall } from '@/data/hooks';
import { Button } from '@/components/ui/button';
import { Kbd } from '@/components/bayle/badge';
import { Segmented, Switch, UnitInput } from '@/components/bayle/controls';
import { cn } from '@/lib/utils';
import { useSettingsCtx } from './context';
import { getValue, isChanged, liveHelp, type RowDef, type SettingPath } from './schema';
import { ThemePicker } from './ThemePicker';
import { ActionControl, LabelExtra } from './rowExtras';

/** Help text where `backticks` become code. */
function Help({ text }: { text?: string }) {
  if (!text) return null;
  const parts = text.split(/`([^`]+)`/);
  return <div className="mt-[3px] max-w-[70ch] text-ui leading-[1.45] text-t3">{parts.map((p, i) => (i % 2 ? <code key={i}>{p}</code> : p))}</div>;
}

const countSchema = z.object({
  n: z.string().trim().regex(/^\d+$/, 'A whole number.').transform(Number).pipe(z.number().min(1, 'At least 1.').max(999, 'At most 999.')),
});

/** A whole number that saves when you leave the box or press Enter. Invalid input shows why and isn't saved. */
function NumberCommit({ path, unit }: { path: SettingPath; unit: string }) {
  const { settings, set } = useSettingsCtx();
  const saved = String(getValue(settings, path) ?? '');
  // `values` keeps the box in step with the saved value while you aren't editing it.
  const form = useForm<z.input<typeof countSchema>, unknown, z.output<typeof countSchema>>({ resolver: zodResolver(countSchema), values: { n: saved }, mode: 'onChange' });
  const error = form.formState.errors.n?.message;
  const commit = form.handleSubmit(({ n }) => { if (String(n) !== saved) set(path, n); });
  const { onBlur, ...field } = form.register('n');
  return (
    <span className="inline-flex flex-col items-end gap-1">
      <UnitInput unit={unit} inputMode="numeric" aria-label={unit} aria-invalid={!!error} {...field}
        onBlur={(e) => { void onBlur(e); void commit(); }} onKeyDown={(e) => e.key === 'Enter' && (e.currentTarget as HTMLInputElement).blur()} />
      {error && <span role="alert" className="text-xs text-bad">{error}</span>}
    </span>
  );
}

function PathBox({ path }: { path: string }) {
  return (
    <div className="mt-[7px] flex max-w-[560px] items-center gap-[7px] rounded-sm border border-line bg-bg px-2.5 py-1.5 font-mono text-xs break-all text-t2">
      <CheckCircle2 className="size-[13px] shrink-0 text-ok" aria-label="Found" />{path}
    </div>
  );
}

function PathControls({ row }: { row: RowDef }) {
  const { settings, set } = useSettingsCtx();
  const call = useCall();
  const p = row.paths[0]!;
  const current = String(getValue(settings, p) ?? '');
  const pick = row.kind.type === 'path' ? row.kind.pick : 'none';
  const change = async () => {
    const chosen = await call((a) => (pick === 'file' ? a.pickFile({ title: `Choose ${row.label}` }) : a.pickFolder({ title: `Choose ${row.label}` })));
    if (chosen) set(p, chosen);
  };
  return <>
    <Button size="sm" variant="ghost" onClick={() => void call((a) => a.openPath(current))}>Open</Button>
    {pick !== 'none' && <Button size="sm" onClick={() => void change()}>Change…</Button>}
  </>;
}

function Control({ row }: { row: RowDef }): ReactNode {
  const { settings, set, games } = useSettingsCtx();
  const k = row.kind;
  const p = row.paths[0];
  switch (k.type) {
    case 'switch': return <Switch checked={getValue(settings, p!) === true} onCheckedChange={(on) => set(p!, on)} aria-label={row.label} />;
    case 'segmented': return <Segmented aria-label={row.label} options={k.options} value={String(getValue(settings, p!))} onChange={(v) => set(p!, k.numeric ? Number(v) : v)} />;
    case 'perGame': return <>{row.paths.map((gp, i) => (
      <span key={gp.join('.')} className="inline-flex h-7 items-center gap-[7px] rounded-sm border border-line pr-2.5 pl-[7px] text-ui text-t2">
        <Switch size="sm" checked={getValue(settings, gp) === true} onCheckedChange={(on) => set(gp, on)} aria-label={`${row.label}: ${row.labels?.[i] ?? games[i]?.name}`} />{row.labels?.[i]}
      </span>))}</>;
    case 'units': return <>{row.paths.map((up, i) => <NumberCommit key={up.join('.')} path={up} unit={k.units[i] ?? ''} />)}</>;
    case 'path': return <PathControls row={row} />;
    case 'action': return <ActionControl row={row} />;
    case 'shortcut': return <span className="flex items-center gap-[3px]">{k.keys.map((x) => <Kbd key={x}>{x}</Kbd>)}</span>;
    default: return null;
  }
}

/**
 * One setting: label (with the changed dot and Reset), help, and its control.
 * Theme puts its picker under the label; paths show the folder in a box.
 */
export function SettingRow({ row }: { row: RowDef }) {
  const { settings, defaults, info, set, reset } = useSettingsCtx();
  const changed = isChanged(row, settings, defaults);
  if (row.kind.type === 'shortcut') {
    return (
      <div className="flex items-center justify-between gap-3 border-b border-line py-2 text-body text-t2">
        <span>{row.label}</span><Control row={row} />
      </div>
    );
  }
  const wide = row.kind.type === 'theme';
  return (
    <div id={`row-${row.id}`} className={cn('grid gap-6 border-b border-line py-3.5 last:border-b-0', wide ? 'grid-cols-1 gap-3' : 'grid-cols-[1fr_auto] items-start max-[560px]:grid-cols-1 max-[560px]:gap-2.5')} data-changed={changed || undefined}>
      <div className="min-w-0">
        <div className="relative flex items-center gap-2 text-emphasis font-[550]">
          {changed && <span aria-label="Changed from the default" className="absolute top-1/2 -left-[13px] size-1.5 -translate-y-1/2 rounded-full bg-accent" />}
          {row.label}
          <LabelExtra row={row} />
          {changed && <button type="button" onClick={() => reset([row])} className="rounded-xs px-1.5 py-px text-caption font-medium text-t3 hover:bg-accent-soft hover:text-accent" title="Back to the default">Reset</button>}
        </div>
        <Help text={liveHelp(row, info?.me3Version)} />
        {row.kind.type === 'path' && <PathBox path={String(getValue(settings, row.paths[0]!) ?? '')} />}
      </div>
      {wide
        ? <ThemePicker value={getValue(settings, row.paths[0]!) as ThemeName} onChange={(t) => set(row.paths[0]!, t)} />
        : <div className="flex min-h-[22px] flex-wrap items-center justify-end gap-1.5 pt-px">{<Control row={row} />}</div>}
    </div>
  );
}
