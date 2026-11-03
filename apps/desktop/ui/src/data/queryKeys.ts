import type { BackendEvent } from '@/api';

/** One place for cache keys, so invalidation can't drift. */
export const qk = {
  appInfo: ['appInfo'] as const,
  games: ['games'] as const,
  profiles: (gameId: string) => ['profiles', gameId] as const,
  profile: (profileId: string) => ['profile', profileId] as const,
  modFiles: (profileId: string, modId: string) => ['modFiles', profileId, modId] as const,
  attachable: (profileId: string, modId: string) => ['attachable', profileId, modId] as const,
  saves: (gameId: string) => ['saves', gameId] as const,
  copies: (gameId: string) => ['copies', gameId] as const,
  configFiles: (profileId: string) => ['configFiles', profileId] as const,
  configFile: (profileId: string, id: string) => ['configFile', profileId, id] as const,
  build: (profileId: string) => ['build', profileId] as const,
  buildPlan: (profileId: string) => ['buildPlan', profileId] as const,
  setup: (id: string) => ['setup', id] as const,
  setupUsers: (id: string) => ['setupUsers', id] as const,
  activity: ['activity'] as const,
  log: (id: string) => ['log', id] as const,
  settings: ['settings'] as const,
  defaultSettings: ['defaultSettings'] as const,
};

/** Which cached queries a backend "changed" event makes stale. */
export const scopeRoots: Record<Extract<BackendEvent, { type: 'changed' }>['scope'], string[]> = {
  profiles: ['games', 'profiles', 'profile', 'modFiles', 'attachable', 'configFiles', 'setupUsers', 'build', 'buildPlan'],
  saves: ['saves', 'copies'],
  activity: ['activity'],
  settings: ['settings'],
  configs: ['configFiles', 'configFile', 'setup', 'setupUsers', 'profile', 'build', 'buildPlan'],
};
