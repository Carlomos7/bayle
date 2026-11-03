/**
 * The Overhaul sheet over the engine (routers/mod_configs.py setup routes, routers/mod_install.py overhaul routes;
 * modules/mods/mod_configs.py for the form, adapters/overhauls/basic.py for the file actions).
 *
 * Three kinds of setup id, all opened by getSetup(id, profileId):
 *  - `install:<install id>`: the open download in the install dialog (modInstall.ts holds it). Its form is the
 *    engine's preview (mod_install_preview); installing is mod_install_finish with `overhaul` ticked.
 *  - `mod:<folder>`: one of the profile's own mods, set up as its overhaul (setup_candidates, overhaul_form with a
 *    folder, check_install_setup, install_setup).
 *  - anything else (`overhaul`, or the setup file's path from Mod Configs): the profile's own saved setup
 *    (overhaul_form, save_setup, then apply_setup so every profile using it follows).
 *
 * The engine's form is natives (DLLs), a Files table (file → action, by kind of file) and texts (file → table); the
 * UI's setup is dlls + files. What is read is kept per setup id until it is saved or installed, because a write needs
 * the sha, stamp or install id of that read and the original rows.
 *
 * Not here: turning the overhaul off (mod_configs_check_turn_off / _turn_off) and the installer-made "install from a
 * folder" routes (mod_install_check_overhaul_install / _overhaul_install, which install_finish covers for a
 * download): BayleApi has no member for them.
 */
import type { BayleApi } from '../../BayleApi';
import type { FileAction, Leftover, OverhaulSetup, Recipe } from '../../types';
import type { components } from '../engine.gen';
import type { Gateway } from '../hub';
import { GatewayError } from '../transport';
import { baseName, bytes, forget, runJob, said } from './modsCommon';
import type { Held } from './modInstall';

const OP = {
  candidates: 'mod_configs_setup_candidates',
  form: 'mod_configs_overhaul_form',
  saveSetup: 'mod_configs_save_setup',
  setupUsers: 'mod_configs_setup_users',
  applySetup: 'mod_configs_apply_setup',
  checkInstallSetup: 'mod_configs_check_install_setup',
  installSetup: 'mod_configs_install_setup',
  preview: 'mod_install_preview',
  finish: 'mod_install_finish',
  removeChoices: 'mod_install_overhaul_remove_choices',
  checkRemove: 'mod_install_check_overhaul_remove',
  remove: 'mod_install_overhaul_remove',
  leftovers: 'mod_install_leftovers',
  cleanLeftovers: 'mod_install_leftovers_clean',
} as const;

/* ------------------------------------------------------------------ engine shapes */

type S = components['schemas'];
// The contract types the form's rows, setup and choices as dicts, so these four stay hand-written (mod_configs.py, basic.py).
interface EngineNative { file: string; load_early: boolean; initializer: string | null; after_others: boolean }
interface EngineFile { file: string; kind: string; action: string; choices: string[]; target: string }
interface EngineText { file: string; table: string; tables?: string[] }
interface EngineSetup { config: { id: string; label: string; basic?: { version?: string | null } | null }; verified: boolean; level: string; folder: string | null; path: string | null; sha: string | null }
interface EngineForm extends Omit<S['OverhaulForm'], 'setup' | 'choices'> { setup: EngineSetup; choices: { natives: EngineNative[]; files: EngineFile[]; texts: EngineText[] } }
interface EnginePreview extends Omit<S['OverhaulPreview'], 'natives' | 'files' | 'texts'> { natives: EngineNative[]; files: EngineFile[]; texts: EngineText[] }
type EngineLeftover = S['LeftoverFolder'];
/** SetupForm (routers/mod_install.py): what the engine takes back. `health` is left out: the sheet has no log check, so the engine keeps its own. */
interface SetupForm { natives: EngineNative[]; files: Record<string, string>; tables: Record<string, string> }

/** What one read left behind. */
interface Ctx {
  profile: string;
  rows: EngineFile[];
  texts: EngineText[];
  /** The form as read, to tell whether the player changed it (an unchanged one sends no setup: the engine keeps a matched config as it is). */
  initial: string;
  // The write this setup is for.
  edit?: { path: string; sha: string; overhaulId: string };
  download?: Held;
  mod?: { folder: string; name: string; overhaulId: string };
}

const WHAT: Record<string, string> = { regulation: 'game parameters', binder: 'game data', game: 'game file', settings: 'settings', loose: 'other file' };

const refuse = (code: string, message: string) => new GatewayError({ code, message });
/** A refusal list as one error, the way the engine words a failed start. */
const refused = (code: string, why: string[]) => refuse(code, why.join(' ') || "Bayle can't do this.");

/* ------------------------------------------------------------------ rows ⇄ the UI's files */

/** The engine's action for a row, in the UI's words: parameters combine, other binders merge, "whole" is a plain copy. */
function actionOf(r: EngineFile): FileAction {
  if (r.action === 'merge') return r.kind === 'regulation' ? 'combine' : 'merge';
  return r.action === 'whole' ? 'copy' : (r.action as FileAction);
}

function engineAction(r: EngineFile, a: FileAction, target?: string): string {
  switch (a) {
    case 'combine': case 'merge': return 'merge';
    case 'copy': return r.kind === 'regulation' || r.kind === 'binder' ? 'whole' : 'copy';
    case 'place': return `place:${target ?? r.target}`;
    case 'text': return r.action; // texts are set by their table, not by this action
    default: return a;
  }
}

const formOf = (s: OverhaulSetup, ctx: Pick<Ctx, 'rows' | 'texts'>): SetupForm => ({
  natives: s.dlls.map((d) => ({ file: d.name, load_early: d.loadEarly, initializer: d.initFunction || null, after_others: d.loadAfterOthers })),
  files: Object.fromEntries(ctx.rows.map((r) => {
    const f = s.files.find((x) => x.path === r.file);
    return [r.file, engineAction(r, f ? f.action : actionOf(r), f?.target)];
  })),
  // shortcut: the sheet cannot pick a text table or switch texts off, so each keeps the table the engine chose; upgrade with a table select in FilesStep.
  tables: Object.fromEntries(ctx.texts.map((t) => [t.file, t.table])),
});

function toSetup(id: string, name: string, version: string, folder: string, form: Pick<EnginePreview, 'natives' | 'files' | 'texts'>, saved: boolean, recipe?: Recipe): OverhaulSetup {
  const setup: OverhaulSetup = {
    id, name, version,
    // shortcut: the engine gives no save date, so a saved setup says only that it was saved.
    savedOn: saved ? 'earlier' : null,
    gameDir: folder,
    dlls: form.natives.map((n) => ({ name: n.file, loadEarly: n.load_early, loadAfterOthers: n.after_others, initFunction: n.initializer ?? '' })),
    files: [
      ...form.files.map((r) => ({ path: r.file, what: WHAT[r.kind] ?? r.kind, action: actionOf(r), ...(r.action === 'place' ? { target: r.target } : {}) })),
      ...form.texts.map((t) => ({ path: t.file, what: 'menu text', action: 'text' as const })),
    ],
    // shortcut: the engine counts no text languages for a download; shown as 0 until it does.
    languages: 0,
  };
  if (recipe) setup.recipe = recipe;
  return setup;
}

/* ------------------------------------------------------------------ the adapter */

/** downloads: the install dialog's open installs (modInstall.ts), by source path. */
export function overhaulApi(gateway: Gateway, downloads: Map<string, Held>): Partial<BayleApi> {
  const call = <T>(operation: string, params?: Record<string, unknown>) => gateway.call<T>(operation, params).catch((e: unknown) => { throw said(e); });
  const read = new Map<string, Ctx>();

  const keep = (id: string, ctx: Omit<Ctx, 'initial'>, s: OverhaulSetup) => { read.set(id, { ...ctx, initial: JSON.stringify(formOf(s, ctx)) }); return s; };

  async function ofDownload(id: string, profileId: string): Promise<OverhaulSetup> {
    const installId = id.slice('install:'.length);
    const held = [...downloads.values()].find((h) => h.installId === installId);
    if (!held || held.profile !== profileId) throw refuse('unknown_install', 'The download was closed. Read it again.');
    const p = await call<EnginePreview>(OP.preview, { install_id: installId, name: held.plan.name });
    // shortcut: the engine's lines and notes have no place in the sheet; only its refusals show, as a mismatch the player can't install past.
    const recipe: Recipe | undefined = p.refusals.length || p.mode === 'matched'
      ? { source: p.editable ? 'yours' : 'bundled', forVersion: '', base: 'unknown', check: p.refusals.length ? 'mismatch' : 'match', ...(p.refusals.length ? { differences: p.refusals } : {}) }
      : undefined;
    return keep(id, { profile: profileId, rows: p.files, texts: p.texts, download: held }, toSetup(id, held.plan.name, '', held.plan.unpacked ?? held.plan.root ?? '', p, false, recipe));
  }

  function ofForm(id: string, profileId: string, f: EngineForm, ctx: Pick<Ctx, 'edit' | 'mod'>, name: string): OverhaulSetup {
    const version = f.setup.config.basic?.version ?? '';
    const recipe: Recipe | undefined = f.new ? undefined : { source: f.setup.verified ? 'bundled' : 'yours', forVersion: version, base: 'unknown', check: 'match' };
    return keep(id, { profile: profileId, rows: f.choices.files, texts: f.choices.texts, ...ctx }, toSetup(id, name, version, f.setup.folder ?? '', f.choices, !f.new, recipe));
  }

  return {
    async getSetup(id, profileId) {
      if (id.startsWith('install:')) return ofDownload(id, profileId);
      if (id.startsWith('mod:')) {
        const folder = id.slice('mod:'.length).replaceAll('\\', '/').toLowerCase();
        const { mods } = await call<{ mods: { name: string; id: string; folder: string }[] }>(OP.candidates, { profile: profileId });
        const m = mods.find((c) => c.folder.replaceAll('\\', '/').toLowerCase() === folder);
        if (!m) throw refuse('not_found', 'That mod is no longer in the profile.');
        const f = await call<EngineForm>(OP.form, { profile: profileId, folder: m.folder, name: m.name, overhaul_id: m.id });
        return ofForm(id, profileId, f, { mod: { folder: m.folder, name: m.name, overhaulId: m.id } }, m.name);
      }
      const f = await call<EngineForm>(OP.form, { profile: profileId });
      const { path, sha, config } = f.setup;
      if (!path || !sha) throw refuse('not_found', 'This profile has no saved overhaul setup.');
      // A hand-written setup has no form to show, and saving the form would replace what it says.
      if (f.setup.level !== 'basic') throw refuse('advanced_setup', `${config.label} was written by hand. Edit it as text on Mod Configs.`);
      return ofForm(id, profileId, f, { edit: { path, sha, overhaulId: config.id } }, config.label);
    },

    // Only a saved setup (opened to edit) has users; a download or a mod being set up has none yet.
    // shortcut: `running` is always false; the engine's refusal while the game runs still stops the save.
    async setupUsers(id) {
      const ctx = read.get(id);
      if (!ctx?.edit) return [];
      const { profiles } = await call<{ profiles: string[] }>(OP.setupUsers, { profile: ctx.profile, overhaul_id: ctx.edit.overhaulId });
      return profiles.map((p) => ({ profileId: p, name: baseName(p).replace(/\.me3$/i, ''), running: false }));
    },

    async saveSetup(setup) {
      const ctx = read.get(setup.id);
      if (!ctx?.edit) throw refuse('stale', 'This setup was not opened here, or changed since. Open it again, then save.');
      const { path, sha, overhaulId } = ctx.edit;
      read.delete(setup.id); // the sha moves with the write; the sheet reads again
      await call(OP.saveSetup, { profile: ctx.profile, path, expect: sha, form: formOf(setup, ctx) });
      const { result, entry } = await runJob(gateway, OP.applySetup, { profile: ctx.profile, overhaul_id: overhaulId }, 'rebuild');
      forget(ctx.profile);
      const names = (result as { profiles?: string[] } | undefined)?.profiles ?? [];
      return { entry, message: `Saved ${setup.name}'s setup`, ...(names.length ? { detail: `Applied to ${names.join(', ')}` } : {}) };
    },

    async installOverhaul(profileId, setup) {
      const ctx = read.get(setup.id);
      if (!ctx || ctx.profile !== profileId || ctx.edit) throw refuse('stale', 'This setup was not opened here, or changed since. Open it again, then install.');
      const form = formOf(setup, ctx);
      const changed = JSON.stringify(form) !== ctx.initial;
      let run: Awaited<ReturnType<typeof runJob>>;
      if (ctx.download) {
        const { installId, plan, stamp } = ctx.download;
        // The check: the engine's preview of this form, which says what would refuse it.
        const p = await call<EnginePreview>(OP.preview, { install_id: installId, name: plan.name, ...(changed ? { setup: form } : {}) });
        if (p.refusals.length) throw refused('cannot_install', p.refusals);
        const choices = { name: plan.name, id: plan.id ?? '', variant: plan.variant || null, exclude: [], overhaul: true, ...(changed ? { setup: form } : {}) };
        run = await runJob(gateway, OP.finish, { install_id: installId, choices, expect: stamp }, 'install');
        for (const [source, h] of downloads) if (h.installId === installId) downloads.delete(source); // the install ends with the job
      } else {
        const { folder, name, overhaulId } = ctx.mod!;
        const body = { profile: profileId, folder, name, overhaul_id: overhaulId, form };
        const plan = await call<S['SetupPlan']>(OP.checkInstallSetup, body);
        if (plan.refusals.length) throw refused('cannot_set_up', plan.refusals);
        run = await runJob(gateway, OP.installSetup, { ...body, expect: plan.stamp }, 'install');
      }
      read.delete(setup.id);
      forget(profileId);
      return { entry: run.entry, message: `Installed ${setup.name}` };
    },

    async removeOverhaul(profileId) {
      // The rows an installer-made overhaul offers to put back come ticked as the engine suggests; the dialog asks for none.
      const { ticked } = await call<{ ticked?: number[] }>(OP.removeChoices, { profile: profileId });
      const chosen = ticked ?? [];
      const plan = await call<S['OverhaulPlan']>(OP.checkRemove, { profile: profileId, chosen });
      if (plan.refusals.length) throw refused('cannot_remove', plan.refusals);
      const { entry } = await runJob(gateway, OP.remove, { profile: profileId, chosen, revert: false, expect: plan.stamp }, 'install');
      forget(profileId);
      return { entry, message: `Removed ${plan.label}` };
    },

    async listLeftovers(profileId): Promise<Leftover[]> {
      const l = await call<S['Leftovers']>(OP.leftovers, { profile: profileId });
      const row = (f: EngineLeftover, backup: boolean): Leftover => ({ path: f.path, label: f.label || baseName(f.path), size: bytes(f.size), backup });
      return [...l.folders.map((f) => row(f, false)), ...l.backups.map((f) => row(f, true))];
    },

    async cleanLeftovers(profileId, paths) {
      const { entry } = await runJob(gateway, OP.cleanLeftovers, { profile: profileId, paths }, 'install');
      return { entry, message: paths.length === 1 ? 'Moved the leftover to the Recycle Bin' : `Moved ${paths.length} leftovers to the Recycle Bin` };
    },
  };
}
