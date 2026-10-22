import { useQuery } from "@tanstack/react-query";
import { Outlet, useNavigate } from "@tanstack/react-router";
import { open as pickPath } from "@tauri-apps/plugin-dialog";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { pageKey } from "@/api/events";
import { useApi } from "@/api/backend";
import type { ShellState } from "@/api/types";
import { sonnerToasts, toProblem } from "@/components/toasts";
import { useTheme, type ThemeSetting } from "@/theme/ThemeProvider";
import { ShellActionsContext, type ShellActions } from "./context";
import { actionForKey } from "./keys";
import { Me3Dialog, type Me3Facts } from "./Me3Dialog";
import { ENTRY_PAGES } from "./menus";
import { NewProfileDialog, type NewProfileOffer } from "./NewProfileDialog";
import { useShellOp } from "./ops";
import { pathForPage } from "./pages";
import { Rail } from "./Rail";
import { TopBar } from "./TopBar";
import { UpdateNotices } from "./UpdateNotices";

const RAIL_KEY = "bayle.railCollapsed";
const loadRail = () => {
  try {
    return localStorage.getItem(RAIL_KEY) === "1";
  } catch {
    return false;
  }
};

/** A modal is open: the keys that start things stay quiet (the dialog owns the keyboard). */
const modalOpen = () => !!document.querySelector('[role="dialog"], [role="alertdialog"]');

export function Shell() {
  const api = useApi();
  const navigate = useNavigate();
  const op = useShellOp();
  const { setTheme } = useTheme();
  const { data: shell, error } = useQuery({
    queryKey: pageKey("shell"),
    queryFn: () => api.get<ShellState>("/v1/pages/shell"),
  });
  const [railCollapsed, setRailCollapsed] = useState(loadRail);
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);
  const [modeMenuOpen, setModeMenuOpen] = useState(false);
  const [offer, setOffer] = useState<NewProfileOffer | null>(null);
  const [me3, setMe3] = useState<Me3Facts | null>(null);

  const go = useCallback((page: string) => {
    const to = pathForPage(page);
    if (to) void navigate({ to });
  }, [navigate]);

  const pickFolder = useCallback(async (title: string) => {
    const got = await pickPath({ directory: true, title });
    return typeof got === "string" ? got : null;
  }, []);

  const actions = useMemo<ShellActions>(() => {
    const openNewProfile = async () => {
      const got = await op<NewProfileOffer>("shell.new_profile_offer");
      if (got) setOffer(got);
    };
    const addProfile = async () => {
      const path = await pickPath({
        title: "Pick a me3 profile",
        filters: [
          { name: "me3 profile or installation.json", extensions: ["me3", "json"] },
          { name: "All files", extensions: ["*"] },
        ],
      });
      if (typeof path === "string") await op("shell.add_profile", { path });
    };
    const launch = (mode?: string) => void op("shell.launch", mode ? { mode } : {});
    const setGame = (key: string) => void op("shell.set_game", { key });
    const cycleGame = (step: 1 | -1) => {
      const games = shell?.games ?? [];
      const at = games.findIndex((g) => g.checked);
      const next = games[(at + step + games.length) % games.length];
      if (next && games.length > 1) setGame(next.key);
    };
    const place = (which: string) => void op("shell.open_place", { which });
    const run = (id: string) => {
      const [, , mode] = id.split(".");
      if (id.startsWith("game.launch.")) return launch(mode);
      if (id.startsWith("game.")) return setGame(id.slice(5));
      if (id.startsWith("view.theme.")) return setTheme(id.slice(11) as ThemeSetting);
      switch (id) {
        case "file.new":
          return void openNewProfile();
        case "file.add":
          return void addProfile();
        case "file.profile_folder":
          return place("profile");
        case "file.game_folder":
          return place("game");
        case "file.exit":
          return void getCurrentWindow().close();
        case "view.rail":
          return toggleRail();
        case "help.how":
          return place("readme");
        case "help.updates":
          return void op("shell.check_updates", { force: true });
        case "help.logs_folder":
          return place("logs");
        case "help.logs_save":
          return void (async () => {
            const folder = await pickFolder("Save the logs into...");
            if (!folder) return;
            const saved = await op<{ path: string }>("shell.save_logs", { folder });
            if (saved) sonnerToasts.notice(`Logs saved: ${saved.path}`);
          })();
        case "help.me3":
          return void (async () => {
            const got = await op<{ facts: Me3Facts }>("shell.me3");
            if (got) setMe3(got.facts);
          })();
        case "help.steam":
          return void (async () => {
            const got = await op<{ changed: string[] }>("shell.steam_shortcuts");
            if (got) {
              sonnerToasts.notice(
                got.changed.length ? `Steam shortcuts now start Bayle: ${got.changed.join(", ")}` : "No Steam shortcut needed changing.",
              );
            }
          })();
      }
      const page = ENTRY_PAGES[id];
      if (page) go(page);
    };
    // the links of views/topbar.py
    const follow = (action: string) => {
      switch (action) {
        case "new_profile":
          return void openNewProfile();
        case "pick_profile":
          return setProfileMenuOpen(true);
        case "open_steam":
          return place("steam");
        case "clear_dead":
          return void op("shell.clear_dead_processes");
        case "stop_rebuild":
          return void op("shell.stop_rebuild");
        case "settings:me3":
          void op("shell.me3");
          return go("settings");
        case "settings:locations":
          return go("settings");
        case "mod_configs":
          return go("modConfigs");
        default:
          return go(action); // mods, activity
      }
    };
    function toggleRail() {
      setRailCollapsed((c) => {
        try {
          localStorage.setItem(RAIL_KEY, c ? "0" : "1");
        } catch {
          // storage blocked: lasts until restart
        }
        return !c;
      });
    }
    return {
      follow,
      openNewProfile: () => void openNewProfile(),
      addProfile: () => void addProfile(),
      launch,
      cycleGame,
      setGame,
      toggleRail,
      railCollapsed,
      profileMenuOpen,
      setProfileMenuOpen,
      modeMenuOpen,
      setModeMenuOpen,
      run,
    };
  }, [op, shell, go, setTheme, pickFolder, railCollapsed, profileMenuOpen, modeMenuOpen]);

  // Qt's keys: Ctrl+L launch, Ctrl+Shift+L the mode menu, Ctrl+Tab the next game, Ctrl+N, Ctrl+Q, F1, Ctrl+1..5
  const actionsRef = useRef(actions);
  useEffect(() => {
    actionsRef.current = actions;
  });
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const action = actionForKey(e);
      if (!action || modalOpen()) return;
      e.preventDefault();
      const a = actionsRef.current;
      if (action === "launch") a.launch();
      else if (action === "launch.menu") a.setModeMenuOpen(true);
      else if (action === "game.next") a.cycleGame(1);
      else if (action === "game.prev") a.cycleGame(-1);
      else a.run(action);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);

  return (
    <ShellActionsContext value={actions}>
      <div className="flex h-full flex-col bg-surface-page">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-surface-card focus:p-2"
        >
          Skip to content
        </a>
        <TopBar shell={shell} error={error ? toProblem(error).message : undefined} />
        <UpdateNotices notices={shell?.updates?.notices ?? []} />
        <div className="flex min-h-0 flex-1">
          <Rail unseen={shell?.unseen ?? 0} collapsed={railCollapsed} />
          <main id="main" tabIndex={-1} className="min-w-0 flex-1 overflow-auto p-6 outline-none">
            <div className="mx-auto max-w-[var(--content-max-w)]">
              <Outlet />
            </div>
          </main>
        </div>
      </div>
      <NewProfileDialog offer={offer} onClose={() => setOffer(null)} />
      <Me3Dialog facts={me3} onClose={() => setMe3(null)} />
    </ShellActionsContext>
  );
}
