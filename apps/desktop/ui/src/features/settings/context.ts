import { createContext, useContext } from 'react';
import type { AppInfo, Game, Settings } from '@/api';
import type { RowDef, SettingPath, SettingValue } from './schema';

/** What every row needs: current values, defaults, and how to change them. */
export interface SettingsCtx {
  settings: Settings;
  defaults: Settings;
  info?: AppInfo;
  games: Game[];
  set: (path: SettingPath, value: SettingValue) => void;
  reset: (rows: RowDef[]) => void;
  askResetAll: () => void;
}

export const SettingsContext = createContext<SettingsCtx | null>(null);

export function useSettingsCtx(): SettingsCtx {
  const c = useContext(SettingsContext);
  if (!c) throw new Error('useSettingsCtx must be used inside the Settings page');
  return c;
}
