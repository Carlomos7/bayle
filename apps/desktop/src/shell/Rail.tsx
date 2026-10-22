import { Link } from "@tanstack/react-router";
import { PAGES } from "./pages";

/** The navigation rail. Collapses to icons under 820 px (the Qt compactBelow) or when the player folds it. */
export function Rail({ unseen, collapsed = false }: { unseen: number; collapsed?: boolean }) {
  return (
    <nav
      aria-label="Pages"
      className={`flex shrink-0 flex-col gap-0.5 border-r border-border-hairline bg-surface-bar p-1 pt-3 ${
        collapsed ? "w-[var(--rail-collapsed-w)]" : "w-[var(--rail-w)] max-[820px]:w-[var(--rail-collapsed-w)]"
      }`}
    >
      {PAGES.map(({ path, label, icon: Icon, shortcut }) => (
        <Link
          key={path}
          to={path}
          title={shortcut ? `${label} (Ctrl+${shortcut})` : label}
          aria-keyshortcuts={shortcut ? `Control+${shortcut}` : undefined}
          activeProps={{ "aria-current": "page", className: "bg-smear-selected text-gold-text" }}
          inactiveProps={{ className: "text-text-primary hover:bg-smear-hover" }}
          className={`relative flex h-10 items-center gap-3 rounded-control px-3 text-body transition-colors duration-fast ${
            path === "/settings" ? "mt-auto" : ""
          }`}
        >
          <Icon aria-hidden className="size-5 shrink-0" />
          <span className={collapsed ? "sr-only" : "max-[820px]:sr-only"}>{label}</span>
          {path === "/activity" && unseen > 0 ? (
            <span
              aria-label={`${unseen} failed since you last looked`}
              className="ml-auto grid h-[18px] min-w-[18px] place-items-center rounded-pill bg-status-badge px-1 text-caption font-semibold text-white"
            >
              {unseen > 99 ? "99+" : unseen}
            </span>
          ) : null}
        </Link>
      ))}
    </nav>
  );
}
