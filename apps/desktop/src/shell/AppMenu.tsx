import { Check, ChevronRight } from "lucide-react";
import { Menubar } from "radix-ui";
import type { ShellState } from "@/api/types";
import { useTheme } from "@/theme/ThemeProvider";
import { useShellActions } from "./context";
import { enabled, MENUS, MODES, type MenuEntry } from "./menus";
import { menuContent, menuHint, menuItem } from "./menuStyle";

/** The menu bar (views/menu.py): File, Profile, Game, Saves, View, Help. */
export function AppMenu({ shell }: { shell: ShellState | undefined }) {
  const { railCollapsed, run } = useShellActions();
  const { theme } = useTheme();

  const checked = (e: MenuEntry) => {
    const [kind, value] = (e.checked ?? "").split(":");
    return (kind === "theme" && theme === value) || (kind === "game" && shell?.game === value);
  };
  const entries = (menu: (typeof MENUS)[number]): MenuEntry[] => {
    if (menu.id !== "game") return menu.entries;
    const idle = !!shell?.game_ready && shell.pill.state !== "busy" && !shell.game_running;
    return [
      ...(shell?.games ?? []).map((g) => ({ id: `game.${g.key}`, label: g.name, checked: `game:${g.key}` })),
      { id: "", label: "", separator: true },
      ...MODES.map(([m, word]) => ({
        id: `game.launch.${m}`,
        label: `Launch ${word}`,
        rule: idle ? undefined : ("profile" as const), // the backend refuses with the reason when it cannot
      })),
    ];
  };

  function item(e: MenuEntry, i: number) {
    if (e.separator) return <Menubar.Separator key={i} className="my-1 h-px bg-border-hairline" />;
    if (e.submenu)
      return (
        <Menubar.Sub key={e.id}>
          <Menubar.SubTrigger className={menuItem}>
            {e.label}
            <ChevronRight aria-hidden className="ml-auto size-4" />
          </Menubar.SubTrigger>
          <Menubar.Portal>
            <Menubar.SubContent className={menuContent} sideOffset={4}>
              {e.submenu.map(item)}
            </Menubar.SubContent>
          </Menubar.Portal>
        </Menubar.Sub>
      );
    const label = e.id === "view.rail" ? (railCollapsed ? "Expand navigation" : "Collapse navigation") : e.label;
    return (
      <Menubar.Item
        key={e.id}
        className={menuItem}
        disabled={!enabled(e.rule, shell)}
        onSelect={() => run(e.id)}
        aria-keyshortcuts={e.shortcut?.replace("Ctrl", "Control")}
      >
        <span aria-hidden className="grid size-4 place-items-center">
          {checked(e) ? <Check className="size-4" /> : null}
        </span>
        {label}
        {e.shortcut ? <span className={menuHint}>{e.shortcut}</span> : null}
      </Menubar.Item>
    );
  }

  return (
    <Menubar.Root aria-label="Menu" className="flex items-center gap-0.5">
      {MENUS.map((menu) => (
        <Menubar.Menu key={menu.id}>
          <Menubar.Trigger className="h-6 rounded-control px-2.5 text-caption outline-none data-[highlighted]:bg-smear-hover data-[state=open]:bg-surface-pressed focus-visible:ring-2 focus-visible:ring-glow-ring">
            {menu.title}
          </Menubar.Trigger>
          <Menubar.Portal>
            <Menubar.Content className={menuContent} align="start" sideOffset={2}>
              {entries(menu).map(item)}
            </Menubar.Content>
          </Menubar.Portal>
        </Menubar.Menu>
      ))}
    </Menubar.Root>
  );
}
