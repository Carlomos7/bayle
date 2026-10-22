import { createRootRoute, createRoute, createRouter, lazyRouteComponent, redirect, type AnyRoute, type RouteComponent } from "@tanstack/react-router";
import { SettingsPage } from "@/pages/settings/SettingsPage";
import { TokenPreview } from "@/theme/TokenPreview";
import { PAGES } from "@/shell/pages";
import { Shell } from "@/shell/Shell";
import { ActivityPage } from "@/pages/activity/ActivityPage";
import { ModsPage } from "@/pages/mods/ModsPage";
import { PlaceholderPage } from "@/pages/PlaceholderPage";
import { ProfileTransferPage } from "@/pages/profile-transfer/ProfileTransferPage";
import { SavesPage } from "@/pages/saves/SavesPage";

/** The pages that are built, by key; the rest show a placeholder. One line per page keeps page merges apart. */
const BUILT: Record<string, RouteComponent> = {
  activity: ActivityPage,
  // the editor (CodeMirror) is the heavy part: loaded with the page
  mods: ModsPage,
  modConfigs: lazyRouteComponent(() => import("@/pages/mod-configs/ModConfigsPage"), "ModConfigsPage"),
  profileTransfer: ProfileTransferPage,
  saves: SavesPage,
  settings: SettingsPage,
};

export function buildRouter(history?: Parameters<typeof createRouter>[0]["history"]) {
  const root = createRootRoute({ component: Shell });
  const index = createRoute({
    getParentRoute: () => root,
    path: "/",
    beforeLoad: () => {
      throw redirect({ to: "/mods" });
    },
  });
  const pages = PAGES.map((p) =>
    createRoute({
      getParentRoute: () => root,
      path: p.path,
      component: BUILT[p.key] ?? (() => <PlaceholderPage title={p.label} />),
    }),
  );
  const routes: AnyRoute[] = [index, ...pages];
  if (import.meta.env.DEV) {
    routes.push(createRoute({ getParentRoute: () => root, path: "/dev/tokens", component: TokenPreview }));
  }
  return createRouter({ routeTree: root.addChildren(routes), history });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof buildRouter>;
  }
}
