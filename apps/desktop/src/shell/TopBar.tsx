import { Check, ChevronDown, Gamepad2, Loader2, Menu, Plus } from "lucide-react";
import { DropdownMenu } from "radix-ui";
import { useEffect, useState } from "react";
import type { ShellState } from "@/api/types";
import { useTheme } from "@/theme/ThemeProvider";
import { AppMenu } from "./AppMenu";
import { useShellActions } from "./context";
import { LaunchPill } from "./LaunchPill";
import { menuContent, menuHint, menuItem } from "./menuStyle";
import { useShellOp } from "./ops";

const TONES: Record<string, string> = {
  danger: "text-status-danger",
  warning: "text-status-warning",
  accent: "text-accent",
};

/** Under 820 px (the Qt compactBelow). */
function useCompact() {
  const query = "(max-width: 819.98px)";
  const [compact, setCompact] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setCompact(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return compact;
}

const dropButton =
  "flex h-9 items-center gap-2 rounded-card border border-border-edge bg-fill-ghost px-3 text-body outline-none hover:bg-fill-ghost-hover focus-visible:ring-2 focus-visible:ring-glow-ring disabled:text-text-disabled data-[state=open]:bg-fill-ghost-hover";

/** Status text plus the link that fixes it (StatusLine.qml). A click on the words opens the job in Activity. */
function StatusLine({ shell, error, className }: { shell: ShellState | undefined; error?: string; className?: string }) {
  const { follow } = useShellActions();
  const st = shell?.status;
  const text = error ?? st?.text ?? "Connecting to the engine...";
  const tone = TONES[error ? "danger" : (st?.tone ?? "")] ?? "text-text-secondary";
  const toActivity = !error && !!st?.to_activity;
  return (
    <div className={`flex min-w-0 items-center gap-2 text-caption ${className ?? ""}`}>
      {st?.busy ? <Loader2 aria-hidden className="size-3 shrink-0 animate-spin text-accent" /> : null}
      <p role="status" className={`min-w-0 truncate ${tone}`} title={toActivity ? "Open in Activity" : text}>
        {toActivity ? (
          <button type="button" className="max-w-full truncate hover:underline" onClick={() => follow("activity")}>
            {text}
          </button>
        ) : (
          text
        )}
      </p>
      {st?.link ? (
        <>
          <span aria-hidden className="text-text-secondary">·</span>
          <button
            type="button"
            className="shrink-0 text-accent underline outline-none focus-visible:ring-2 focus-visible:ring-glow-ring"
            onClick={() => follow(st.link!.action)}
          >
            {st.link.text}
          </button>
        </>
      ) : null}
    </div>
  );
}

/** Two rows (TopBar.qml): the menu bar, then collapse, Launch, game, profile and the status line. */
export function TopBar({ shell, error }: { shell: ShellState | undefined; error?: string }) {
  const { logoSrc } = useTheme();
  const { railCollapsed, toggleRail, setGame, profileMenuOpen, setProfileMenuOpen, follow, addProfile } = useShellActions();
  const op = useShellOp();
  const compact = useCompact();
  const busy = shell?.pill.state === "busy";
  const current = shell?.profiles[shell.profile_index];
  return (
    <header className="shrink-0 border-b border-border-edge">
      <div className="flex h-8 items-center gap-2 bg-surface-chrome px-3">
        <img src={logoSrc} alt="Bayle" className="size-[18px]" />
        <AppMenu shell={shell} />
      </div>
      <div className="flex h-[var(--bar-row-h)] items-center gap-3 bg-surface-bar px-2">
        <button
          type="button"
          aria-label={railCollapsed ? "Expand navigation" : "Collapse navigation"}
          onClick={toggleRail}
          className="grid size-9 place-items-center rounded-control outline-none hover:bg-fill-ghost-hover focus-visible:ring-2 focus-visible:ring-glow-ring"
        >
          <Menu aria-hidden className="size-5" />
        </button>
        <LaunchPill shell={shell} />
        <DropdownMenu.Root>
          <DropdownMenu.Trigger disabled={busy} aria-label="Game" className={`${dropButton} w-44`}>
            <Gamepad2 aria-hidden className="size-4 shrink-0" />
            <span className="truncate">{shell?.game_name ?? "Bayle"}</span>
            <ChevronDown aria-hidden className="ml-auto size-3 shrink-0" />
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content align="start" sideOffset={4} className={menuContent}>
              {(shell?.games ?? []).map((g) => (
                <DropdownMenu.CheckboxItem key={g.key} checked={g.checked} onSelect={() => setGame(g.key)} className={menuItem}>
                  <span aria-hidden className="size-4">
                    <DropdownMenu.ItemIndicator>
                      <Check className="size-4" />
                    </DropdownMenu.ItemIndicator>
                  </span>
                  {g.name}
                  <span className={menuHint}>{g.status}</span>
                </DropdownMenu.CheckboxItem>
              ))}
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
        <DropdownMenu.Root open={profileMenuOpen} onOpenChange={setProfileMenuOpen}>
          <DropdownMenu.Trigger disabled={busy} aria-label="Profile" className={`${dropButton} w-56`}>
            <span className="truncate">{current ?? "No profile"}</span>
            <ChevronDown aria-hidden className="ml-auto size-3 shrink-0" />
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content align="start" sideOffset={4} className={menuContent}>
              {(shell?.profiles ?? []).map((label, i) => (
                <DropdownMenu.CheckboxItem
                  key={`${i}-${label}`}
                  checked={i === shell?.profile_index}
                  onSelect={() => void op("shell.pick_profile", { index: i })}
                  className={menuItem}
                >
                  <span aria-hidden className="size-4">
                    <DropdownMenu.ItemIndicator>
                      <Check className="size-4" />
                    </DropdownMenu.ItemIndicator>
                  </span>
                  {label}
                </DropdownMenu.CheckboxItem>
              ))}
              <DropdownMenu.Separator className="my-1 h-px bg-border-hairline" />
              <DropdownMenu.Item className={menuItem} onSelect={() => addProfile()}>
                <span aria-hidden className="size-4" />
                Add existing profile...
              </DropdownMenu.Item>
              <DropdownMenu.Item className={menuItem} onSelect={() => follow("new_profile")}>
                <Plus aria-hidden className="size-4" />
                New profile...
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
        {compact ? null : <StatusLine shell={shell} error={error} />}
      </div>
      {/* under 820 px the status has no room in the bar: it gets a line of its own */}
      {compact ? <StatusLine shell={shell} error={error} className="h-7 bg-surface-bar px-4" /> : null}
    </header>
  );
}
