import { useCallback, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import type { ActionResult, BayleApi, Game, Profile } from '@/api';
import { useApi } from './ApiProvider';
import { qk } from './queryKeys';
import { toast } from '@/state/toasts';
import { useUi } from '@/state/ui';

/* ------------------------------------------------------------------ reads */

export const useAppInfo = () => { const api = useApi(); return useQuery({ queryKey: qk.appInfo, queryFn: () => api.getAppInfo() }); };
export const useGames = () => { const api = useApi(); return useQuery({ queryKey: qk.games, queryFn: () => api.getGames() }); };
export const useProfiles = (gameId: string) => { const api = useApi(); return useQuery({ queryKey: qk.profiles(gameId), queryFn: () => api.listProfiles(gameId) }); };
export const useProfile = (profileId: string | undefined) => { const api = useApi(); return useQuery({ queryKey: qk.profile(profileId ?? ''), queryFn: () => api.getProfile(profileId!), enabled: !!profileId }); };
export const useModFiles = (profileId: string | undefined, modId: string | undefined) => { const api = useApi(); return useQuery({ queryKey: qk.modFiles(profileId ?? '', modId ?? ''), queryFn: () => api.listModFiles(profileId!, modId!), enabled: !!profileId && !!modId }); };
export const useAttachable = (profileId: string | undefined, modId: string | undefined) => { const api = useApi(); return useQuery({ queryKey: qk.attachable(profileId ?? '', modId ?? ''), queryFn: () => api.listAttachableConfigs(profileId!, modId!), enabled: !!profileId && !!modId }); };
export const useSaves = (gameId: string) => { const api = useApi(); return useQuery({ queryKey: qk.saves(gameId), queryFn: () => api.listSaves(gameId) }); };
export const useCopies = (gameId: string) => { const api = useApi(); return useQuery({ queryKey: qk.copies(gameId), queryFn: () => api.listCopies(gameId) }); };
export const useConfigFiles = (profileId: string | undefined) => { const api = useApi(); return useQuery({ queryKey: qk.configFiles(profileId ?? ''), queryFn: () => api.listConfigFiles(profileId!), enabled: !!profileId }); };
export const useConfigFile = (profileId: string | undefined, id: string | undefined) => { const api = useApi(); return useQuery({ queryKey: qk.configFile(profileId ?? '', id ?? ''), queryFn: () => api.getConfigFile(profileId!, id!), enabled: !!profileId && !!id }); };
export const useBuild = (profileId: string | undefined) => { const api = useApi(); return useQuery({ queryKey: qk.build(profileId ?? ''), queryFn: () => api.getBuild(profileId!), enabled: !!profileId }); };
export const useBuildPlan = (profileId: string | undefined) => { const api = useApi(); return useQuery({ queryKey: qk.buildPlan(profileId ?? ''), queryFn: () => api.previewBuild(profileId!), enabled: !!profileId }); };
export const usePieceSearch = (profileId: string | undefined, query: string) => { const api = useApi(); return useQuery({ queryKey: [...qk.build(profileId ?? ''), 'search', query], queryFn: () => api.searchPieces(profileId!, query), enabled: !!profileId && query.trim().length > 0, placeholderData: (prev) => prev }); };
export const useOrderSuggestion = (profileId: string | undefined) => { const api = useApi(); return useQuery({ queryKey: [...qk.build(profileId ?? ''), 'order'], queryFn: () => api.suggestOrder(profileId!), enabled: !!profileId }); };
export const useSetup = (id: string | undefined) => { const api = useApi(); return useQuery({ queryKey: qk.setup(id ?? ''), queryFn: () => api.getSetup(id!), enabled: !!id }); };
export const useSetupUsers = (id: string | undefined) => { const api = useApi(); return useQuery({ queryKey: qk.setupUsers(id ?? ''), queryFn: () => api.setupUsers(id!), enabled: !!id }); };
export const useActivity = () => { const api = useApi(); return useQuery({ queryKey: qk.activity, queryFn: () => api.listActivity() }); };
export const useLog = (id: string | undefined) => { const api = useApi(); return useQuery({ queryKey: qk.log(id ?? ''), queryFn: () => api.getLog(id!), enabled: !!id }); };
export const useSettings = () => { const api = useApi(); return useQuery({ queryKey: qk.settings, queryFn: () => api.getSettings() }); };
export const useDefaultSettings = () => { const api = useApi(); return useQuery({ queryKey: qk.defaultSettings, queryFn: () => api.getDefaultSettings(), staleTime: Infinity }); };

/** The selected game and its active profile, the two things almost every page needs. */
export function useCurrent(): { game: Game | undefined; profile: Profile | undefined; loading: boolean } {
  const gameId = useUi((s) => s.gameId);
  const games = useGames();
  const game = games.data?.find((g) => g.id === gameId) ?? games.data?.[0];
  const prof = useProfile(game?.supported ? game.activeProfileId : undefined);
  return { game, profile: prof.data, loading: games.isLoading || prof.isLoading };
}

/* ------------------------------------------------------------------ writes */

export interface RunOptions {
  /** Override the toast title (defaults to the backend's message). */
  title?: string;
  /** Skip the success toast, e.g. for inline edits that show their own state. */
  quiet?: boolean;
}

/**
 * Run a change against the backend, then toast it with Undo and refresh
 * cached data. Errors become a toast with the backend's sentence.
 *
 *   const { run, pending } = useAction();
 *   run((api) => api.setModsEnabled(profileId, [id], false));
 */
export function useAction() {
  const api = useApi();
  const qc = useQueryClient();
  const [pending, setPending] = useState(0);

  const undo = useCallback(async (entryId: string) => {
    try {
      const r = await api.undo(entryId);
      toast({ kind: 'info', title: r.message });
    } catch (e) {
      toast({ kind: 'error', title: (e as Error).message });
    } finally {
      await qc.invalidateQueries();
    }
  }, [api, qc]);

  const run = useCallback(async <T extends ActionResult>(fn: (api: BayleApi) => Promise<T>, opts: RunOptions = {}): Promise<T | undefined> => {
    setPending((n) => n + 1);
    try {
      const r = await fn(api);
      if (!opts.quiet) {
        toast({
          kind: 'success',
          title: opts.title ?? r.message,
          detail: r.detail,
          action: r.entry.undoable ? { label: r.entry.undoLabel ?? 'Undo', run: () => void undo(r.entry.id) } : undefined,
        });
      }
      return r;
    } catch (e) {
      // Stopped by the player, or the engine is away: say so plainly, not as a failure.
      const code = (e as { code?: string }).code;
      toast({ kind: code === 'cancelled' ? 'info' : code === 'engine_unavailable' || code === 'engine_restarted' ? 'warn' : 'error', title: (e as Error).message });
      return undefined;
    } finally {
      setPending((n) => n - 1);
      await qc.invalidateQueries();
    }
  }, [api, qc, undo]);

  return { run, undo, pending: pending > 0 };
}

/**
 * For calls that change something but are not undoable actions (switching
 * profile, changing a setting): await, refresh caches, toast errors.
 */
export function useCall() {
  const api = useApi();
  const qc = useQueryClient();
  return useCallback(async <T,>(fn: (api: BayleApi) => Promise<T>, success?: { title: string; detail?: string }): Promise<T | undefined> => {
    try {
      const r = await fn(api);
      if (success) toast({ kind: 'info', title: success.title, detail: success.detail });
      return r;
    } catch (e) {
      toast({ kind: 'error', title: (e as Error).message });
      return undefined;
    } finally {
      await qc.invalidateQueries();
    }
  }, [api, qc]);
}
