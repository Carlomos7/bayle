import { useWatch, type UseFormReturn } from 'react-hook-form';
import type { Mod, NativeOptions } from '@/api';
import { Checkbox, Input, Select, Switch } from '@/components/bayle/controls';
import { useMods } from '../controller';
import { NO_NATIVE, type ModOptions } from '../modOptions';
import { Group, Row, FieldError } from './parts';
import { Identity } from './Identity';

/* ------------------------------------------------------------------ Options tab (id 'loading', kept for links) */

export function LoadingTab({ mod: m, form }: { mod: Mod; form: UseFormReturn<ModOptions> }) {
  const c = useMods();
  const others = c.profile.mods.filter((x) => x.kind === 'package' && x.id !== m.id);
  const draft = useWatch({ control: form.control }) as ModOptions;
  const errors = form.formState.errors;
  const set = (d: ModOptions) => {
    for (const k of Object.keys(d) as (keyof ModOptions)[]) {
      if (JSON.stringify(d[k]) !== JSON.stringify(draft[k])) form.setValue(k, d[k], { shouldDirty: true, shouldValidate: true });
    }
  };
  const nat: NativeOptions = draft.native ?? NO_NATIVE;
  const setNat = (patch: Partial<NativeOptions>) => set({ ...draft, native: { ...nat, ...patch } });
  return (
    <div className="flex flex-col gap-3">
      <Identity mod={m} />
      <Group title="In this profile">
        <Row label="Active" help="Off keeps it in the profile, and me3 skips it at launch.">
          <Switch checked={draft.enabled} disabled={!!m.missing} onCheckedChange={(enabled) => set({ ...draft, enabled })} aria-label="Active" />
        </Row>
      </Group>
      {m.kind === 'package' ? (
        <Group title="Load order">
          <Row stacked label="Package id" htmlFor="mp-pid" help="The name other mods use to load before or after this one.">
            <Input id="mp-pid" className="font-mono" aria-invalid={!!errors.packageId} {...form.register('packageId')} />
            <FieldError message={errors.packageId?.message} />
          </Row>
          <Row stacked label="Loads after" help={<>Tick the mods this one must come after. <b className="font-medium text-t2">Optional</b> means the game still starts if that mod is missing.</>}>
            {others.length ? (
              <ul className="m-0 list-none divide-y divide-line rounded-sm border border-line p-0">
                {others.map((o) => {
                  const la = draft.loadAfter.find((x) => x.packageId === o.packageId);
                  const toggle = (on: boolean) => set({ ...draft, loadAfter: on ? [...draft.loadAfter, { packageId: o.packageId, optional: false }] : draft.loadAfter.filter((x) => x.packageId !== o.packageId) });
                  return (
                    <li key={o.id} className="flex h-9 items-center gap-2.5 px-2.5">
                      <Checkbox checked={!!la} onCheckedChange={toggle} aria-label={`Load after ${o.packageId}`} />
                      <span className="flex-1 truncate font-mono text-ui">{o.packageId}</span>
                      <label className="flex items-center gap-1.5 text-xs text-t3">
                        <Checkbox checked={!!la?.optional} disabled={!la} aria-label={`${o.packageId} is optional`}
                          onCheckedChange={(optional) => set({ ...draft, loadAfter: draft.loadAfter.map((x) => (x.packageId === o.packageId ? { ...x, optional } : x)) })} />optional
                      </label>
                    </li>
                  );
                })}
              </ul>
            ) : <p className="m-0 text-xs text-t3">No other package in this profile.</p>}
          </Row>
          <Row label="Loads last" help="Built on top of every mod above it, so nothing may load after it. Big mods that replace most of the game need this.">
            <Switch checked={!!draft.staysLast} onCheckedChange={(staysLast) => set({ ...draft, staysLast })} aria-label="Stays last" />
          </Row>
          {draft.staysLast && (
            <Row stacked label="File it rebuilds" htmlFor="mp-rb" help="Usually regulation.bin, the game's parameters.">
              <Input id="mp-rb" className="font-mono" aria-invalid={!!errors.rebuildFile} {...form.register('rebuildFile')} />
              <FieldError message={errors.rebuildFile?.message} />
            </Row>
          )}
        </Group>
      ) : (
        <Group title="Loading">
          <Row label="Optional" help="If the DLL is missing or fails, the game starts anyway.">
            <Switch checked={nat.optional} onCheckedChange={(optional) => setNat({ optional })} aria-label="Optional" />
          </Row>
          <Row label="Start early" help={<>Starts before the game sets itself up. Seamless Co-op needs this. <code>load_early</code></>}>
            <Switch checked={nat.loadEarly} onCheckedChange={(loadEarly) => setNat({ loadEarly })} aria-label="Start early" />
          </Row>
          <Row stacked label="When it loads" htmlFor="mp-init" help="Call a function in the DLL, or wait a moment, once it is loaded.">
            <div className="flex gap-1.5">
              <Select id="mp-init" className="w-[150px]" value={nat.initializer.kind} onChange={(e) => setNat({ initializer: { kind: e.target.value as NativeOptions['initializer']['kind'], value: nat.initializer.value } })}>
                <option value="none">Nothing</option><option value="function">Call a function</option><option value="delay">Wait (ms)</option>
              </Select>
              {nat.initializer.kind !== 'none' && <Input className="font-mono" aria-label="Function name or delay" placeholder={nat.initializer.kind === 'delay' ? '1000' : 'ModInit'} aria-invalid={!!errors.native?.initializer?.value} {...form.register('native.initializer.value')} />}
            </div>
            <FieldError message={errors.native?.initializer?.value?.message} />
          </Row>
          <Row stacked label="When the game closes" htmlFor="mp-fin" help="A function in the DLL to call on the way out. Leave empty if its readme doesn't mention one.">
            <Input id="mp-fin" className="font-mono" placeholder="Function name" aria-invalid={!!errors.native?.finalizer} {...form.register('native.finalizer')} />
            <FieldError message={errors.native?.finalizer?.message} />
          </Row>
        </Group>
      )}
    </div>
  );
}
