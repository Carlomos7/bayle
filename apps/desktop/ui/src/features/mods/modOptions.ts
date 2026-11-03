import { z } from 'zod';
import type { Mod, NativeOptions } from '@/api';

/** The options the mod panel edits. Saved together with updateMod. */
export type ModOptions = Pick<Mod, 'enabled' | 'packageId' | 'loadAfter' | 'staysLast' | 'rebuildFile' | 'native'>;

export const pickOptions = (m: Mod): ModOptions => structuredClone({ enabled: m.enabled, packageId: m.packageId, loadAfter: m.loadAfter, staysLast: m.staysLast, rebuildFile: m.rebuildFile, native: m.native });

const native = z.object({
  loadEarly: z.boolean(),
  optional: z.boolean(),
  initializer: z.object({ kind: z.enum(['none', 'function', 'delay']), value: z.string().trim() }),
  finalizer: z.string().trim().regex(/^([A-Za-z_]\w*)?$/, 'A function name: letters, numbers and _.'),
}).superRefine((n, ctx) => {
  const { kind, value } = n.initializer;
  if (kind === 'function' && !/^[A-Za-z_]\w*$/.test(value)) ctx.addIssue({ code: 'custom', path: ['initializer', 'value'], message: 'A function name: letters, numbers and _.' });
  if (kind === 'delay' && !(/^\d+$/.test(value) && Number(value) <= 60000)) ctx.addIssue({ code: 'custom', path: ['initializer', 'value'], message: 'Milliseconds, from 0 to 60000.' });
});

/**
 * Rules for one mod's options. Package ids must be unique in the profile
 * because other mods refer to them in load_after.
 */
export function modOptionsSchema(mod: Mod, otherPackageIds: readonly string[]) {
  const taken = new Set(otherPackageIds.map((p) => p.toLowerCase()));
  return z.object({
    enabled: z.boolean(),
    packageId: mod.kind === 'package'
      ? z.string().trim().min(1, 'Other mods need a package id to refer to.')
        .regex(/^[\w.-]+$/, 'Letters, numbers, dots, dashes and _ only.')
        .refine((v) => !taken.has(v.toLowerCase()), 'Another mod in this profile uses that id.')
      : z.string(),
    loadAfter: z.array(z.object({ packageId: z.string(), optional: z.boolean() })),
    staysLast: z.boolean().optional(),
    rebuildFile: z.string().trim().optional(),
    native: native.optional(),
  }).superRefine((o, ctx) => {
    if (o.staysLast && !o.rebuildFile) ctx.addIssue({ code: 'custom', path: ['rebuildFile'], message: 'Name the file its rebuild tool writes.' });
  });
}

/** A native's options before anything is set. */
export const NO_NATIVE: NativeOptions = { loadEarly: false, optional: false, initializer: { kind: 'none', value: '' }, finalizer: '' };
