/**
 * The install dialog over the engine (routers/mod_install.py, modules/mods/mod_install.py): previewInstall opens the
 * download (the engine unpacks and plans it and holds it by an install id), install finishes it with what the dialog
 * ticked.
 *
 * The BayleApi has no "close" or "replan" calls, so this adapter keeps the open install itself, by source path, with
 * the profile's stamp the engine gave. Opening another download closes the one before; install ends its own. A
 * dialog cancelled and never followed by another install keeps its unpacked copy until then.
 * shortcut: no cancel hook in BayleApi to close the open install at once, upgrade with a closeInstall member.
 *
 * Overhaul downloads (a recipe or an overhaul hint) install as ordinary mods here, with a warning: the overhaul flows
 * (mod_install_*overhaul*, preview) are the next batch.
 */
import type { BayleApi } from '../../BayleApi';
import type { InstallPreview } from '../../types';
import type { Gateway } from '../hub';
import { GatewayError } from '../transport';
import { forget, runJob, said } from './modsCommon';

const OP = {
  sources: 'mod_install_sources',
  open: 'mod_install_open',
  replan: 'mod_install_replan',
  close: 'mod_install_close',
  finish: 'mod_install_finish',
} as const;

/** The plan (modules/mods/install.py _plan + library facts), the parts used here. */
interface EnginePlan {
  kind: 'package' | 'native' | 'me3' | 'profile' | 'unknown';
  name: string;
  id?: string;
  variant?: string;
  exists?: boolean;
  id_taken?: boolean;
  name_problem?: string;
  already_listed?: string[];
  contents?: { name: string; group: string; size: number; on: boolean }[];
  library?: { blocked?: boolean };
  option?: 'plain' | 'suggested' | 'matched' | 'refused';
}
interface Opened { install_id: string; plan: EnginePlan; overhaul_on: boolean; stamp: [number, number] | null }

interface Held { installId: string; profile: string; plan: EnginePlan; stamp: [number, number] | null }

const WHAT: Record<string, string> = {
  game: 'game files', regulation: 'game parameters', dll: 'DLL', settings: 'settings', doc: 'notes', profile: 'a me3 profile',
  loader: 'another mod loader', files: "the mod's files", other: 'not recognised',
};

const bytes = (n: number) => (n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : n < 1024 ** 3 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${(n / 1024 ** 3).toFixed(1)} GB`);

function toPreview(source: string, plan: EnginePlan): InstallPreview {
  const warnings: string[] = [];
  if (plan.name_problem) warnings.push(plan.name_problem);
  if (plan.id_taken) warnings.push(`Another mod in this profile already uses the id "${plan.id}".`);
  if (plan.already_listed?.length) warnings.push('This mod is already in the profile, so installing updates it.');
  if (plan.library?.blocked) warnings.push("A shared copy of this mod can't be updated from here.");
  if (plan.option === 'matched' || plan.option === 'suggested') warnings.push('This download looks like an overhaul. It installs as an ordinary mod here.');
  return {
    source,
    detectedAs: plan.kind === 'native' ? 'native' : 'package',
    name: plan.name,
    // shortcut: the engine reads no version from a download, shown empty until it does.
    items: (plan.contents ?? []).map((c) => ({ path: c.name, what: WHAT[c.group] ?? c.group, include: c.on, size: bytes(c.size) })),
    warnings,
  };
}

export function installApi(gateway: Gateway): Partial<BayleApi> {
  const call = <T>(operation: string, params?: Record<string, unknown>) => gateway.call<T>(operation, params).catch((e: unknown) => { throw said(e); });
  /** At most one install is open: the dialog shows one download at a time. */
  const open = new Map<string, Held>();

  const closeAll = async () => {
    for (const [source, h] of [...open]) {
      open.delete(source);
      await gateway.call(OP.close, { install_id: h.installId }).catch(() => undefined);
    }
  };

  return {
    async previewInstall(source) {
      if (!source.profileId) throw new GatewayError({ code: 'invalid_params', message: 'Pick a profile to install into first.' });
      const { usable } = await call<{ usable: string[]; skipped: string[] }>(OP.sources, { paths: [source.path] });
      if (!usable.length) throw new GatewayError({ code: 'not_installable', message: 'Bayle can install a folder, a .zip, .7z or .rar, or a .dll.' });
      await closeAll();
      const o = await call<Opened>(OP.open, { profile: source.profileId, source: source.path });
      open.set(source.path, { installId: o.install_id, profile: source.profileId, plan: o.plan, stamp: o.stamp });
      return toPreview(source.path, o.plan);
    },

    async install(profileId, preview) {
      const held = open.get(preview.source);
      if (!held || held.profile !== profileId) throw new GatewayError({ code: 'unknown_install', message: 'The download was closed. Read it again.' });
      const name = preview.name.trim();
      // A name typed in the dialog plans again (the folder, id and what is already taken follow the name).
      if (name && name !== held.plan.name) held.plan = (await call<{ plan: EnginePlan }>(OP.replan, { install_id: held.installId, name, id: '', variant: held.plan.variant || null })).plan;
      const choices = {
        name: held.plan.name,
        id: held.plan.id ?? '',
        variant: held.plan.variant || null,
        exclude: preview.items.filter((i) => !i.include).map((i) => i.path),
      };
      const { result, entry } = await runJob(gateway, OP.finish, { install_id: held.installId, choices, expect: held.stamp }, 'install');
      open.delete(preview.source);
      forget(profileId);
      const r = result as { name: string; update: boolean };
      return { entry, message: `${r.update ? 'Updated' : 'Installed'} ${r.name}` };
    },
  };
}
