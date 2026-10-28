import { createHashHistory, createRouter } from '@tanstack/react-router';
import { routeTree } from './routeTree.gen';

/**
 * Hash history: URLs look like index.html#/mods, so the built app works from
 * file:// in pywebview, QWebEngineView or a PyInstaller bundle, with no server.
 */
export const router = createRouter({
  routeTree,
  history: createHashHistory(),
  defaultPreload: 'intent',
  scrollRestoration: false,
});

declare module '@tanstack/react-router' {
  interface Register { router: typeof router }
}
