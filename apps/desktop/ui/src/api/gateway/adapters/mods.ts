/**
 * The Mods page over the gateway: the mods of a profile (read, switch on/off, reorder, remove, options, rebuild, take
 * over an installer, add a Shared mod to another profile), plus the install dialog (modInstall.ts) and Share setup
 * (shareSetup.ts). Engine side: routers/mods.py, mod_library.py, mod_install.py.
 *
 * `getProfile` belongs to the shell adapter; its `mods` is `readMods(gateway, profileId)` from modsCommon.ts, which also
 * fills the id → index map the writes here use (a miss is read again).
 *
 * Not connected: renaming a mod's display name (the engine renames folders, which this field is not), upgradeMod,
 * listModFiles, copying a Separate mod to another profile, the overhaul flows, and running a rebuild tool the player has
 * not allowed yet (no dialog to allow it).
 */
import type { BayleApi } from '../../BayleApi';
import type { ActionResult, ActivityEntry } from '../../types';
import type { Gateway } from '../hub';
import { GatewayError } from '../transport';
import { installApi } from './modInstall';
import { baseName, forget, guarded, notWired, OP, readFacts, rowOf, runJob, said, type EngineOptions } from './modsCommon';
import { shareSetupApi, type Pickers } from './shareSetup';

const OPS = {
  useChoices: 'mod_library_use_choices',
  use: 'mod_library_use',
  takeoverChoices: 'mod_install_takeover_choices',
  checkTakeover: 'mod_install_check_takeover',
  takeover: 'mod_install_takeover',
} as const;

interface MoveResult { moved: boolean; name: string; problem: string }
interface Plan { label: string; refusals: string[]; stamp: [number, number] | null }
interface UseChoices { name: string; profiles: { profile: string; name: string; has_copy: boolean; uses: boolean }[] }

const INIT_KIND = { none: 0, function: 1, delay: 2 } as const;
const stem = (p: string) => baseName(p).replace(/\.me3$/i, '');
const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);

export function modsApi(gateway: Gateway, pickers: Pickers): Partial<BayleApi> {
  const call = <T>(operation: string, params?: Record<string, unknown>) => gateway.call<T>(operation, params).catch((e: unknown) => { throw said(e); });

  async function rebuild(profileId: string): Promise<ActivityEntry> {
    return (await runJob(gateway, OP.rebuild, { profile: profileId }, 'rebuild')).entry;
  }

  return {
    ...installApi(gateway),
    ...shareSetupApi(gateway, pickers),

    async setModsEnabled(profileId, modIds, enabled) {
      const rows = await Promise.all(modIds.map((id) => rowOf(gateway, profileId, id)));
      await guarded(profileId, async () => {
        for (const r of rows) await call(OP.setEnabled, { profile: profileId, index: r.index, enabled, expect: r.name });
      });
      const what = rows.length === 1 ? rows[0]!.name : `${rows.length} mods`;
      return { message: `${enabled ? 'Turned on' : 'Turned off'} ${what}` };
    },

    async reorderMods(profileId, kind, orderedIds) {
      // A move changes the block indexes after it, so each step reads the profile again; one drag is one step.
      for (let step = 0; step <= orderedIds.length; step++) {
        const facts = await readFacts(gateway, profileId);
        const hidden = new Set(facts.loads_nothing);
        const shown = facts.display[kind] ?? [];
        const wanted = await Promise.all(orderedIds.map((id) => rowOf(gateway, profileId, id)));
        // The engine's positions count every entry of the kind, including the ones that load nothing and have no row.
        const queue = wanted.map((r) => r.index);
        const target = shown.map((i) => (hidden.has(i) ? i : queue.shift() ?? i));
        const at = target.findIndex((i, k) => shown[k] !== i);
        if (at < 0) break;
        const row = wanted.find((r) => r.index === target[at])!;
        const moved = await guarded(profileId, () => call<MoveResult>(OP.move, { profile: profileId, index: row.index, to: at, expect: row.name }));
        forget(profileId);
        if (!moved.moved) throw new GatewayError({ code: 'move_refused', message: moved.problem || `${moved.name} can't go there.` });
        const after = shown.filter((i) => i !== row.index);
        after.splice(at, 0, row.index);
        if (after.every((i, k) => i === target[k])) break;
      }
      return { message: 'Load order changed' };
    },

    async removeMods(profileId, modIds, opts) {
      const rows = await Promise.all(modIds.map((id) => rowOf(gateway, profileId, id)));
      // Taking an entry out renumbers the ones after it, so the last goes first.
      const order = [...rows].sort((a, b) => b.index - a.index);
      let entry: ActivityEntry | undefined;
      await guarded(profileId, async () => {
        for (const r of order) {
          // The page's confirm dialog is the confirmation; the folder goes to the Recycle Bin when that is safe.
          entry = (await runJob(gateway, OP.remove, { profile: profileId, index: r.index, name: r.name, confirmed: true }, 'profile')).entry;
        }
      });
      forget(profileId);
      let detail: string | undefined;
      if (opts?.rebuild) {
        try { await rebuild(profileId); } catch (e) { detail = `The merged game data was not rebuilt: ${(e as Error).message}`; }
      }
      const one = rows.length === 1;
      return {
        message: one ? `Removed ${rows[0]!.name}` : `Removed ${rows.length} mods`,
        detail: detail ?? (one ? undefined : 'Each one has its own Undo in Activity.'),
        // One toast, one Undo: only a single removal offers it.
        ...(one && entry ? { entry } : {}),
      };
    },

    async updateMod(profileId, modId, patch) {
      // shortcut: the engine renames a mod's folder (mods_rename); this field is a display name it has no place for. Upgrade with a display-name store.
      if (patch.name !== undefined) throw notWired('rename a mod (display name)');
      // staysLast is derived by the engine (mods_fix_order restores it), so it is never sent.
      const row = await rowOf(gateway, profileId, modId);
      const { enabled } = patch;
      const options = { ...patch };
      delete options.enabled;
      delete options.staysLast;
      if (!Object.keys(options).length) {
        if (enabled !== undefined) await guarded(profileId, () => call(OP.setEnabled, { profile: profileId, index: row.index, enabled, expect: row.name }));
        return { message: `Saved ${row.name}` };
      }
      await guarded(profileId, async () => {
        // save_options takes every option at once: start from what the engine has and apply the patch.
        const o = await call<EngineOptions>(OP.options, { profile: profileId, index: row.index });
        if (o.name !== row.name) throw new GatewayError({ code: 'stale', message: 'The profile changed; look again.' });
        const n = options.native;
        await call(OP.saveOptions, {
          profile: profileId,
          index: row.index,
          enabled: enabled ?? o.enabled,
          id: options.packageId ?? o.id,
          load_after: options.loadAfter ? options.loadAfter.map((d) => ({ id: d.packageId, optional: d.optional })) : o.load_after,
          load_before: o.load_before,
          optional: n?.optional ?? o.optional,
          load_early: n?.loadEarly ?? o.load_early,
          finalizer: n?.finalizer ?? o.finalizer,
          init_kind: n?.initializer ? INIT_KIND[n.initializer.kind] : o.init_kind,
          init_value: n?.initializer ? n.initializer.value : o.init_value,
          rebuild_file: options.rebuildFile ?? o.rebuild_file,
          expect: row.name,
        });
      });
      forget(profileId);
      return { message: `Saved ${row.name}` };
    },

    async rebuildMerged(profileId) {
      const entry = await rebuild(profileId);
      return { entry, message: 'Rebuilt the merged game data' };
    },

    async takeOverInstaller(profileId) {
      const choices = await call<{ label: string; ticked: number[] }>(OPS.takeoverChoices, { profile: profileId });
      // The UI has no choice step: the rows the installer copied come ticked, and those are what is taken over.
      const plan = await call<Plan>(OPS.checkTakeover, { profile: profileId, chosen: choices.ticked });
      if (plan.refusals.length) throw new GatewayError({ code: 'cannot_take_over', message: plan.refusals[0]! });
      const { entry } = await runJob(gateway, OPS.takeover, { profile: profileId, chosen: choices.ticked, revert: false, expect: plan.stamp }, 'profile');
      forget(profileId);
      return { entry, message: `Took over ${plan.label || choices.label}` };
    },

    // Only a Shared mod can be linked into another profile; the engine has no copy of a Separate one.
    async addModsToProfile(targetProfileId, fromProfileId, modIds): Promise<ActionResult> {
      let entry: ActivityEntry | undefined;
      for (const id of modIds) {
        const row = await rowOf(gateway, fromProfileId, id);
        const choices = await call<UseChoices>(OPS.useChoices, { profile: fromProfileId, index: row.index }).catch((e: unknown) => {
          // shortcut: a Separate mod is not copied between profiles, upgrade when the engine can (share it first, then add).
          if (e instanceof GatewayError && e.code === 'not_shared') throw notWired("add a mod that isn't shared to another profile");
          throw e;
        });
        const to = choices.profiles.find((p) => p.profile.toLowerCase() === targetProfileId.toLowerCase());
        if (!to) throw new GatewayError({ code: 'not_found', message: `${stem(targetProfileId)} can't use ${choices.name}.` });
        if (to.has_copy) throw new GatewayError({ code: 'has_copy', message: `${to.name} has its own copy of ${choices.name}. Remove it there first.` });
        if (to.uses) continue;
        entry = (await runJob(gateway, OPS.use, { profile: fromProfileId, index: row.index, targets: [to.profile] }, 'profile')).entry;
      }
      forget(targetProfileId);
      return { message: `Added ${modIds.length} ${plural(modIds.length, 'mod', 'mods')} to ${stem(targetProfileId)}`, ...(entry && modIds.length === 1 ? { entry } : {}) };
    },

    // shortcut: no engine route lists a mod's files, upgrade when one exists (conflicts.py / profile_mods.package_tree hold the logic).
    async listModFiles() { throw notWired('listModFiles'); },
    // shortcut: the engine has no "newer release" for a mod, upgrade with a release source.
    async upgradeMod() { throw notWired('upgradeMod'); },
  };
}
