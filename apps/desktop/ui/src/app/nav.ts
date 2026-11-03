import { useCallback, useEffect, useRef } from 'react';
import { useNavigate, useRouterState, useSearch } from '@tanstack/react-router';

export type PageId = 'mods' | 'saves' | 'merge' | 'configs' | 'activity' | 'settings';
/** In the order people reach for them; Ctrl+1…6 follow this order. */
export const PAGE_IDS: PageId[] = ['mods', 'saves', 'merge', 'configs', 'activity', 'settings'];

/** The page in view, from the router's location. */
export function usePage(): PageId {
  const path = useRouterState({ select: (s) => s.location.pathname });
  const first = path.split('/')[1] as PageId | undefined;
  return first && PAGE_IDS.includes(first) ? first : 'mods';
}

/**
 * Typed navigation for menus, shortcuts and the command palette.
 * Prefer <Link to="/mods"> in markup; use these from handlers.
 */
export function useGo() {
  const navigate = useNavigate();
  const page = useCallback((p: PageId) => { void navigate({ to: `/${p}` }); }, [navigate]);
  const openMod = useCallback((mod: string) => { void navigate({ to: '/mods', search: { mod } }); }, [navigate]);
  const openConfig = useCallback((file: string) => { void navigate({ to: '/configs', search: { file } }); }, [navigate]);
  const openSettings = useCallback((section: string) => { void navigate({ to: '/settings', search: { section } }); }, [navigate]);
  const openMerge = useCallback((mod?: string, family?: string) => { void navigate({ to: '/merge', search: { mod, family: family as never } }); }, [navigate]);
  return { page, openMod, openConfig, openSettings, openMerge };
}

type RequestRoute = '/mods' | '/configs' | '/settings';
type RequestKey<R extends RequestRoute> = R extends '/mods' ? 'mod' : R extends '/configs' ? 'file' : 'section';

/**
 * One-shot "open this" requests carried in the URL (?mod=, ?file=, ?section=).
 * Calls `onRequest` with the value, then removes it from the URL so Back and
 * reloads don't repeat it.
 */
export function useSearchRequest<R extends RequestRoute>(route: R, key: RequestKey<R>, onRequest: (value: string) => void) {
  const search = useSearch({ strict: false }) as Partial<Record<string, string>>;
  const value = search[key];
  const navigate = useNavigate();
  const handler = useRef(onRequest);
  useEffect(() => { handler.current = onRequest; });
  useEffect(() => {
    if (!value) return;
    handler.current(value);
    // The route is generic here, so TS can't narrow its search type; {} is valid for all three.
    void navigate({ to: route, search: {}, replace: true } as never);
  }, [value, route, navigate]);
}
