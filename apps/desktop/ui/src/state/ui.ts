import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { GameId, LaunchMode } from '@/api';

/**
 * UI-only state that isn't part of the URL and isn't backend data.
 * Where you are lives in the router; profiles, mods and settings live in
 * TanStack Query.
 */
interface UiState {
  gameId: GameId;
  launchMode: LaunchMode;
  /** Failures logged since Activity was last opened, for the rail badge. */
  unseenFailures: number;
  commandOpen: boolean;
  /** The first-run flow was finished or skipped. */
  onboarded: boolean;
  /** One-time explainer cards the user dismissed, by key. */
  seenTips: string[];
  setOnboarded: (v: boolean) => void;
  dismissTip: (key: string) => void;
  setGame: (g: GameId) => void;
  setLaunchMode: (m: LaunchMode) => void;
  addFailure: () => void;
  clearFailures: () => void;
  setCommandOpen: (open: boolean) => void;
}

export const useUi = create<UiState>()(
  persist(
    (set) => ({
      gameId: 'er',
      launchMode: 'Profile',
      unseenFailures: 2,
      commandOpen: false,
      onboarded: false,
      seenTips: [],
      setOnboarded: (onboarded) => set({ onboarded }),
      dismissTip: (key) => set((s) => ({ seenTips: s.seenTips.includes(key) ? s.seenTips : [...s.seenTips, key] })),
      setGame: (gameId) => set({ gameId }),
      setLaunchMode: (launchMode) => set({ launchMode }),
      addFailure: () => set((s) => ({ unseenFailures: s.unseenFailures + 1 })),
      clearFailures: () => set({ unseenFailures: 0 }),
      setCommandOpen: (commandOpen) => set({ commandOpen }),
    }),
    { name: 'bayle-ui', partialize: (s) => ({ gameId: s.gameId, launchMode: s.launchMode, onboarded: s.onboarded, seenTips: s.seenTips }) },
  ),
);
