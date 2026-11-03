/**
 * Mod Configs over the gateway: the profile's settings files, opening and saving one, attaching and detaching.
 *
 * A profile is identified by its .me3 path (the UI's ProfileId); a settings file by its path (ConfigFileId); a mod
 * on this page by the path the engine attaches files to (its DLL or its package folder).
 *
 * Not here: the overhaul setup flows (a later batch), and sharing Seamless Co-op settings
 * (mod_configs_share, _export_share, _check_paste, _paste, and the file stamp mod_configs_stamp): BayleApi has no
 * method for them yet.
 */
import type { BayleApi } from '../../BayleApi';
import type { ActionResult, ConfigFile, ConfigFileRef, ConfigFormat } from '../../types';
import type { components } from '../engine.gen';
import type { Gateway } from '../hub';
import { GatewayError } from '../transport';
import { langOf, parseForm, valueText, type FieldSpot } from './configForm';

/** Operation ids this adapter uses (OpenAPI operationId of the mod_configs router). */
const OP = {
  page: 'mod_configs',
  open: 'mod_configs_open',
  save: 'mod_configs_save',
  attach: 'mod_configs_attach',
  detach: 'mod_configs_detach',
} as const;

/* ------------------------------------------------------------------ what the engine sends (ModConfigsState, ConfigFileRead) */

type S = components['schemas'];
export type EngineConfigFile = S['ConfigFile'];
export type EngineConfigNode = S['ModNode'];
export type EngineConfigState = S['ModConfigsState'];
export type EngineConfigRead = S['ConfigFileRead'];
type EngineSaved = S['ConfigSaved'];

const baseName = (p: string) => p.split(/[\\/]/).pop() ?? p;
const same = (a: string, b: string) => a.replaceAll('\\', '/').toLowerCase() === b.replaceAll('\\', '/').toLowerCase();

const gone = (what: string) => new GatewayError({ code: 'not_found', message: what });
const stale = () => new GatewayError({ code: 'stale', message: 'This file was not opened here, or changed since. Open it again, then save.' });

/** The id a mod has on this page: what files attach to, else the node's own key (Seamless Co-op, the overhaul). */
const modIdOf = (n: EngineConfigNode) => n.target ?? n.key;

interface Listed { ref: ConfigFileRef; node: EngineConfigNode; file: EngineConfigFile }

export function listedFiles(state: EngineConfigState): Listed[] {
  return state.nodes.flatMap((node) => node.files.filter((f) => f.exists).map((file): Listed => {
    const isSetup = file.how === 'overhaul';
    const ref: ConfigFileRef = { id: isSetup ? `setup:${file.path}` : file.path, modId: modIdOf(node), modName: node.name, name: baseName(file.path) };
    if (isSetup) ref.isSetup = true;
    if (node.kind === 'native' && node.target) ref.viaFile = baseName(node.target);
    return { ref, node, file };
  }));
}

const formatOf = (name: string): ConfigFormat => {
  const lang = langOf(name);
  if (lang) return lang;
  const ext = name.slice(name.lastIndexOf('.') + 1).toLowerCase();
  return ext === 'md' ? 'markdown' : ext === 'json' ? 'json' : 'text';
};

/** What a save needs from the read it follows: the file's sha, how to write it, and where each form field sits. */
interface Opened { sha: string; seamless: boolean; spots: Map<string, FieldSpot> }

export function configsApi(gateway: Gateway): Partial<BayleApi> {
  // Saved against the sha the file had when it was read (the engine refuses a changed file with `stale`).
  const opened = new Map<string, Opened>();
  const slot = (profileId: string, id: string) => `${profileId}\n${id}`;
  const state = (profileId: string) => gateway.call<EngineConfigState>(OP.page, { profile: profileId });

  /** The mod (and its file, when named) a call is about: ids come from listConfigFiles. */
  async function resolve(profileId: string, modId: string, fileName?: string) {
    const node = (await state(profileId)).nodes.find((n) => same(modIdOf(n), modId));
    if (!node?.target) throw gone('That mod is no longer in the profile.');
    const file = fileName ? node.files.find((f) => same(baseName(f.path), fileName)) : undefined;
    if (fileName && !file) throw gone(`${fileName} is not beside ${node.name} any more.`);
    return { node, target: node.target, file };
  }

  const done = (message: string, detail?: string): ActionResult => ({ message, ...(detail ? { detail } : {}) });

  return {
    async listConfigFiles(profileId) {
      return listedFiles(await state(profileId)).map((l) => l.ref);
    },

    async getConfigFile(profileId, id): Promise<ConfigFile> {
      const hit = listedFiles(await state(profileId)).find((l) => l.ref.id === id);
      if (!hit) throw gone('That file is no longer listed for this profile.');
      const r = await gateway.call<EngineConfigRead>(OP.open, { profile: profileId, path: hit.file.path });
      const lang = langOf(hit.ref.name);
      const form = lang ? parseForm(lang, r.text) : null;
      opened.set(slot(profileId, id), { sha: r.sha, seamless: hit.file.kind === 'seamless', spots: form?.spots ?? new Map() });
      return { ...hit.ref, path: r.path, format: formatOf(hit.ref.name), ...(form ? { sections: form.sections } : {}), text: r.text };
    },

    async saveConfigFile(profileId, id, change) {
      const was = opened.get(slot(profileId, id));
      if (!was) throw stale();
      const base = { profile: profileId, path: id, expect: was.sha };
      let saved: EngineSaved;
      if ('text' in change) {
        saved = await gateway.call<EngineSaved>(OP.save, { ...base, kind: 'text', text: change.text });
      } else {
        const edits = Object.entries(change.values).map(([k, value]) => {
          const spot = was.spots.get(k);
          if (!spot) throw gone(`${k} is no longer in this file.`);
          return { section: spot.section, key: spot.key, value: valueText(spot, value) };
        });
        saved = await gateway.call<EngineSaved>(OP.save, { ...base, kind: was.seamless ? 'seamless' : 'values', edits });
      }
      opened.delete(slot(profileId, id)); // the sha moved on; the page reads the file again
      // No Activity entry: a save is an immediate write the engine does not log as a job.
      return done(`Saved ${saved.name}`, saved.missing?.length ? `Not in the file, so not written: ${saved.missing.join(', ')}` : undefined);
    },

    async attachConfig(profileId, modId, fileNames) {
      let mod = '';
      for (const name of fileNames) {
        const { node, target, file } = await resolve(profileId, modId, name);
        await gateway.call(OP.attach, { profile: profileId, target, file: file!.path });
        mod = node.name;
      }
      return done(fileNames.length === 1 ? `${fileNames[0]} attached to ${mod}` : `${fileNames.length} files attached to ${mod}`, 'Edit it on Mod Configs.');
    },

    async detachConfig(profileId, modId, fileName) {
      const { node, target, file } = await resolve(profileId, modId, fileName);
      await gateway.call(OP.detach, { profile: profileId, target, file: file!.path });
      return done(`${fileName} detached`, `${node.name}: the file stays where it is.`);
    },

    // The files the engine finds beside the mod without a tie (its `found` ones); a file the player browsed to is not among them.
    async listAttachableConfigs(profileId, modId) {
      const node = (await state(profileId)).nodes.find((n) => same(modIdOf(n), modId));
      return (node?.files ?? []).filter((f) => f.how === 'found' && f.exists).map((f) => baseName(f.path));
    },
  };
}
