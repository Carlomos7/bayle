import { Loader2 } from "lucide-react";
import type { ShellState } from "@/api/types";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/theme/ThemeProvider";

const TONES: Record<string, string> = {
  danger: "text-status-danger",
  warning: "text-status-warning",
  accent: "text-accent",
};

/** Logo, game, profile, the one status line and the Play pill (a placeholder until the launch flow lands). */
export function TopBar({ shell }: { shell: ShellState | undefined }) {
  const { logoSrc } = useTheme();
  const profile = shell?.profiles[shell.profile_index];
  return (
    <header className="flex h-[var(--bar-row-h)] shrink-0 items-center gap-4 border-b border-border-edge bg-surface-bar px-3">
      <img src={logoSrc} alt="Bayle" className="size-[22px]" />
      <span className="font-semibold text-row text-title">{shell?.game_name ?? "Bayle"}</span>
      {profile ? (
        <span className="rounded-tag border border-border-tag px-2 py-0.5 text-caption text-text-secondary" aria-label="Profile">
          {profile}
        </span>
      ) : null}
      <p
        role="status"
        className={`flex min-w-0 items-center gap-2 truncate text-caption ${TONES[shell?.status.tone ?? ""] ?? "text-text-secondary"}`}
      >
        {shell?.status.busy ? <Loader2 aria-hidden className="size-3 animate-spin" /> : null}
        {shell?.status.text ?? "Connecting to the engine..."}
      </p>
      <Button variant="primary" className="ml-auto rounded-pill px-6" disabled={!shell?.pill.can_launch}>
        {shell?.pill.text ?? "Play"}
      </Button>
    </header>
  );
}
