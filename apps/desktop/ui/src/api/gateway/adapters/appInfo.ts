/**
 * About and Updates. The build's facts (version, update channel, data folder, platform) come from Rust (app_info), the
 * me3 version from the engine (settings_me3), and the update check from Rust's signed-manifest check. Both Rust
 * answers work while the engine is down. Installing is `gateway.app.installUpdate` (EngineScreens, Updates dialog).
 *
 * Not connected: me3Latest (the engine has no "latest me3" route). In the browser preview there is no Rust, so the
 * version is the engine's and the data folder is empty.
 */
import type { BayleApi } from '../../BayleApi';
import type { AppInfo } from '../../types';
import type { Gateway } from '../hub';
import { OPERATIONS } from '../protocol';

const OP = { me3: 'settings_me3' } as const;

const PLATFORMS: Record<string, string> = { windows: 'Windows', linux: 'Linux', macos: 'macOS' };

export function appInfoApi(gateway: Gateway): Partial<BayleApi> {
  const info = async (): Promise<AppInfo> => {
    const [shell, me3, health] = await Promise.all([
      gateway.app?.info?.(),
      gateway.call<{ version: string | null }>(OP.me3).catch(() => ({ version: null })),
      gateway.app?.info ? undefined : gateway.call<{ app_version: string }>(OPERATIONS.health).catch(() => undefined),
    ]);
    return {
      version: shell?.version ?? health?.app_version ?? '',
      me3Version: me3.version ?? '',
      platform: shell ? (PLATFORMS[shell.platform] ?? shell.platform) : 'Browser',
      dataFolder: shell?.dataFolder ?? '',
    };
  };

  return {
    getAppInfo: info,

    async checkForUpdates() {
      const [base, found, shell] = await Promise.all([info(), gateway.app?.checkUpdate(), gateway.app?.info?.()]);
      return found ? { ...base, update: { version: found.version, channel: shell?.channel ?? '' } } : base;
    },
  };
}
