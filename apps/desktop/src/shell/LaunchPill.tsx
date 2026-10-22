import { ChevronDown, Loader2, Play } from "lucide-react";
import { DropdownMenu } from "radix-ui";
import type { ShellState } from "@/api/types";
import { cn } from "@/lib/cn";
import { useShellActions } from "./context";
import { menuContent, menuItem } from "./menuStyle";
import { useShellOp } from "./ops";

/**
 * The Launch pill (LaunchPill.qml): the left zone runs the mode, the right zone opens the mode menu. States come from
 * the backend: enabled | busy | running | blocked; the reason is the tooltip (and the status line says it in words).
 */
export function LaunchPill({ shell }: { shell: ShellState | undefined }) {
  const { launch, modeMenuOpen, setModeMenuOpen } = useShellActions();
  const pill = shell?.pill;
  const state = pill?.state ?? "blocked";
  const canRun = !!pill?.can_launch && state === "enabled";
  const showMode = state === "enabled" || state === "blocked";
  const grey = state === "blocked" || state === "running";
  const zone = "flex h-full items-center gap-2 px-4 text-body outline-none focus-visible:ring-2 focus-visible:ring-glow-ring";
  return (
    <div
      title={pill?.reason || undefined}
      className={cn(
        "relative flex h-[var(--control-large-h,36px)] shrink-0 items-center overflow-hidden rounded-card border border-gold-line bg-gold-fill-top font-semibold",
        grey ? "text-text-tertiary opacity-80" : "text-gold-text",
      )}
    >
      {pill?.warn ? (
        <span role="img" aria-label={pill.reason} className="absolute top-1.5 left-1.5 size-2 rounded-full bg-status-warning" />
      ) : null}
      <button
        type="button"
        aria-keyshortcuts="Control+L"
        aria-disabled={!canRun}
        disabled={!canRun}
        onClick={() => launch()}
        className={cn(zone, canRun && "hover:bg-gold-fill-top-hover")}
      >
        {state === "busy" ? <Loader2 aria-hidden className="size-4 animate-spin" /> : <Play aria-hidden className="size-4" />}
        {pill?.text ?? "Launch"}
      </button>
      {showMode ? (
        <DropdownMenu.Root open={modeMenuOpen} onOpenChange={setModeMenuOpen}>
          <DropdownMenu.Trigger
            aria-label={`Launch mode: ${pill?.mode_text ?? ""}`}
            aria-keyshortcuts="Control+Shift+L"
            className={cn(zone, "gap-1.5 font-medium hover:bg-gold-fill-top-hover")}
          >
            <span className="opacity-70">{pill?.mode_text}</span>
            <ChevronDown aria-hidden className="size-3" />
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content align="end" sideOffset={4} className={menuContent}>
              <ModeItems shell={shell} />
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      ) : null}
    </div>
  );
}

function ModeItems({ shell }: { shell: ShellState | undefined }) {
  const op = useShellOp();
  return (
    <DropdownMenu.RadioGroup value={shell?.mode} onValueChange={(mode) => void op("shell.set_mode", { mode })}>
      {(shell?.modes ?? []).map((m) => (
        <DropdownMenu.RadioItem key={String(m.mode)} value={String(m.mode)} className={menuItem}>
          <span aria-hidden className="size-4">
            <DropdownMenu.ItemIndicator>•</DropdownMenu.ItemIndicator>
          </span>
          {String(m.text)}
        </DropdownMenu.RadioItem>
      ))}
    </DropdownMenu.RadioGroup>
  );
}
