import { useQuery } from "@tanstack/react-query";
import { Outlet, useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";
import { pageKey } from "@/api/events";
import { useApi } from "@/api/backend";
import type { ShellState } from "@/api/types";
import { PAGES } from "./pages";
import { Rail } from "./Rail";
import { TopBar } from "./TopBar";

/** Ctrl+1..6 jump to the rail's pages. */
export function usePageShortcuts() {
  const navigate = useNavigate();
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (!e.ctrlKey || e.altKey || e.shiftKey || e.metaKey) return;
      const page = PAGES[Number(e.key) - 1];
      if (!page) return;
      e.preventDefault();
      void navigate({ to: page.path });
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [navigate]);
}

export function Shell() {
  const api = useApi();
  usePageShortcuts();
  const { data: shell } = useQuery({
    queryKey: pageKey("shell"),
    queryFn: () => api.get<ShellState>("/v1/pages/shell"),
  });
  return (
    <div className="flex h-full flex-col bg-surface-page">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-surface-card focus:p-2"
      >
        Skip to content
      </a>
      <TopBar shell={shell} />
      <div className="flex min-h-0 flex-1">
        <Rail unseen={shell?.unseen ?? 0} />
        <main id="main" tabIndex={-1} className="min-w-0 flex-1 overflow-auto p-6 outline-none">
          <div className="mx-auto max-w-[var(--content-max-w)]">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
