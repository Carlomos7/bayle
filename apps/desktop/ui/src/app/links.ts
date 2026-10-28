/** External pages the UI links to. Change them here when the repo moves. */
export const REPO = 'https://github.com/Carlomos7/roundtable-souls';
export const LINKS = {
  repo: REPO,
  releases: `${REPO}/releases`,
  releaseNotes: (version: string) => `${REPO}/releases/tag/v${version}`,
  thirdParty: `${REPO}/blob/main/THIRD_PARTY_NOTICES.md`,
  licence: `${REPO}/blob/main/LICENSE`,
  me3Releases: 'https://github.com/garyttierney/me3/releases',
};
