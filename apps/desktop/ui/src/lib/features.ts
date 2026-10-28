/**
 * Features the UI is ready for but the backend can't feed yet. Flip one on
 * when its data is real; until then the UI shows nothing rather than guesses.
 */
export const FEATURES = {
  /**
   * Mod versions, and the "update available" badges and Update tab that compare them.
   * Off: Bayle has no reliable way to read a mod's version yet (no manifest field, no Nexus lookup).
   */
  modVersions: false,
} as const;
