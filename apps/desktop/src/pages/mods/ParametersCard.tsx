import { Code2, MoreHorizontal, RefreshCw, Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { say } from "./notify";
import { useMods } from "./context";
import { Card, Menu, MenuItem, MenuSep, Pill } from "./ui";

/** Parameters and rebuild: the state pill, the reasons, one main button labelled by the state, Undo rebuild, the overflow. */
export function ParametersCard({ onDetails }: { onDetails(): void }) {
  const { view, words, actions } = useMods();
  const p = view.state.parameters;
  const copy = () => {
    if (!p.fingerprint) return;
    void navigator.clipboard.writeText(p.fingerprint).then(() => say(words.toastFingerprint ?? ""));
  };
  return (
    <section id="parameters" aria-label={words.parameters}>
      <Card className="flex flex-col gap-3 p-4">
        <div className="flex items-center gap-2">
          <Code2 aria-hidden className="size-[18px]" />
          <h2 className="font-semibold text-title">{words.parameters}</h2>
          {p.pill ? <Pill level={p.level || "muted"} icon={p.level === "success" ? "Accept" : p.level === "danger" ? "Cancel" : "Info"} text={p.pill} /> : null}
          <Menu
            label={words.parameters ?? ""}
            trigger={
              <Button aria-label={words.more} title={words.more} className="ml-auto h-8 min-w-0 px-2">
                <MoreHorizontal aria-hidden className="size-4" />
              </Button>
            }
          >
            <MenuItem onSelect={actions.trimBackups}>{words.keepNewest}</MenuItem>
            <MenuItem onSelect={actions.allowTool} disabled={!view.tool_label}>
              {words.allowTool}
            </MenuItem>
            <MenuSep />
            <MenuItem onSelect={onDetails}>{words.details}</MenuItem>
          </Menu>
        </div>
        {p.reasons.length > 0 ? (
          <ul className="flex flex-col gap-1 text-caption text-text-tertiary">
            {p.reasons.map((r) => (
              <li key={r}>• {r}</li>
            ))}
          </ul>
        ) : null}
        {p.blocked ? <p className="text-caption text-status-warning">{p.blocked}</p> : null}
        {p.fingerprint ? (
          <div className="flex items-center gap-2">
            <p className="flex-1 whitespace-pre-line text-caption">
              {p.fingerprint}
              {"\n"}
              {p.fingerprint_note}
            </p>
            <Button onClick={copy}>{words.copy}</Button>
          </div>
        ) : null}
        <div className="flex gap-2">
          {p.action ? (
            <Button
              disabled={!!p.blocked}
              onClick={actions.rebuild}
              className={p.level === "warning" || p.level === "danger" ? "text-accent" : undefined}
            >
              <RefreshCw aria-hidden className="size-4" />
              {p.action}
            </Button>
          ) : null}
          {view.rebuild_undo ? (
            <Button onClick={actions.undoRebuild}>
              <Undo2 aria-hidden className="size-4" />
              {view.rebuild_undo.label}
            </Button>
          ) : null}
        </div>
      </Card>
    </section>
  );
}
