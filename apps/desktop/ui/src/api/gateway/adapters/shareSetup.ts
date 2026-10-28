/**
 * Share setup over the engine's profile transfer (routers/profile_transfer.py): the dialog's "Your setup" is the
 * engine's share list for the profile, and "Save setup file" writes that share list (kind "list": the mods and their
 * options, no mod files; settings files are left out, because the dialog promises their contents stay private).
 *
 * The UI's manifest also has versions, fingerprints and the loader version, which the engine's list does not carry,
 * and "Compare" wants a two-sided diff where the engine only previews an import. Those stay not connected.
 */
import type { BayleApi } from '../../BayleApi';
import type { SetupManifest } from '../../types';
import type { Gateway } from '../hub';
import { baseName, notWired, runJob, said } from './modsCommon';

const OP = { listing: 'profile_transfer', checkExport: 'profile_transfer_check_export', export: 'profile_transfer_export' } as const;

/** The two pickers of the desktop adapter (BayleApi.pickFolder), passed in because this adapter does not own them. */
export type Pickers = Pick<BayleApi, 'pickFile' | 'pickFolder'>;

interface Listing { mods: { key: string; name: string; enabled: boolean; size: number }[]; save_name: string }

const stem = (p: string) => baseName(p).replace(/\.me3$/i, '');

export function shareSetupApi(gateway: Gateway, pickers: Pickers): Partial<BayleApi> {
  const call = <T>(operation: string, params?: Record<string, unknown>) => gateway.call<T>(operation, params).catch((e: unknown) => { throw said(e); });
  const listing = (profile: string) => call<Listing>(OP.listing, { profile });

  return {
    async exportManifest(profileId): Promise<SetupManifest> {
      const l = await listing(profileId);
      const now = new Date();
      return {
        profileName: stem(profileId),
        // shortcut: the share list has no game name, loader version, launch options, hashes or settings fingerprints; empty until the engine adds them.
        game: '',
        me3Version: '',
        madeOn: `today, ${now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false })}`,
        launch: { mode: 'Profile', online: false },
        mods: l.mods.map((m, i) => ({ name: m.name, kind: m.key.startsWith('native:') ? 'native' : 'package', enabled: m.enabled, hash: '', order: i + 1 })),
        configs: [],
      };
    },

    async saveManifest(profileId) {
      const folder = await pickers.pickFolder({ title: 'Save the setup file' });
      if (!folder) return null;
      const chosen = (await listing(profileId)).mods.map((m) => m.key);
      const check = await call<{ size: number }>(OP.checkExport, { profile: profileId, kind: 'list', chosen });
      const { result } = await runJob(gateway, OP.export, { profile: profileId, kind: 'list', name: stem(profileId), folder, chosen, with_configs: false, with_save: false, password: false, expect: check.size }, 'profile');
      return (result as { path: string }).path;
    },

    // shortcut: the engine previews an import (what it would change here), it does not diff two setups, upgrade with a compare route.
    async compareManifest() { throw notWired('compareManifest'); },
  };
}
