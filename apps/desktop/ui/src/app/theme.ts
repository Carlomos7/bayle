import { useEffect } from 'react';
import type { Settings, ThemeName } from '@/api';

const KEY = 'bayle-theme';

/** Resolve "system" against the OS setting. */
export function resolveTheme(t: ThemeName): Exclude<ThemeName, 'system'> {
  if (t !== 'system') return t;
  return matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

/** Apply before React renders, from the last known theme, so there is no flash. */
export function applyCachedTheme() {
  let t: ThemeName = 'dark';
  try { t = (localStorage.getItem(KEY) as ThemeName | null) ?? 'dark'; } catch { /* storage unavailable */ }
  document.documentElement.dataset.theme = resolveTheme(t);
}

/** Keep <html> in step with the appearance settings. */
export function useApplyAppearance(appearance: Settings['appearance'] | undefined) {
  useEffect(() => {
    if (!appearance) return;
    const root = document.documentElement;
    const apply = () => { root.dataset.theme = resolveTheme(appearance.theme); };
    apply();
    root.dataset.effects = appearance.effects;
    root.dataset.density = appearance.density;
    try { localStorage.setItem(KEY, appearance.theme); } catch { /* storage unavailable */ }
    if (appearance.theme !== 'system') return;
    const mq = matchMedia('(prefers-color-scheme: light)');
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, [appearance]);
}
