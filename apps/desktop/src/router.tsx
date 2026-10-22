import { createRootRoute, createRoute, createRouter, redirect, type AnyRoute } from "@tanstack/react-router";
import { AppearanceControls } from "@/theme/AppearanceControls";
import { TokenPreview } from "@/theme/TokenPreview";
import { PAGES } from "@/shell/pages";
import { Shell } from "@/shell/Shell";
import { PlaceholderPage } from "@/pages/PlaceholderPage";

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
      component: () => (
        <PlaceholderPage title={p.label}>{p.key === "settings" ? <AppearanceControls /> : null}</PlaceholderPage>
      ),
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
