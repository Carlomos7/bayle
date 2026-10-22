import { useVirtualizer } from "@tanstack/react-virtual";
import { ChevronDown, ChevronRight, Trash2 } from "lucide-react";
import { Tabs } from "radix-ui";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { DragHandle, useDropSpot } from "./drag";
import { useSavesOps } from "./ops";
import type { BackupRow, LibraryRow } from "./types";
import { Card, hint, IconButton, InfoBar, Menu, MenuItem, MenuSeparator, Pill, sectionTitle } from "./ui";

/** A scrolling area of fixed height whose rows are drawn on demand (long lists stay cheap). */
function VirtualList<T>({
  items,
  label,
  render,
  estimate,
}: {
  items: T[];
  label: string;
  render: (item: T, index: number) => React.ReactNode;
  estimate: (item: T) => number;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line react-hooks/incompatible-library -- the list only reads v during this render
  const v = useVirtualizer({
    count: items.length,
    getScrollElement: () => scroller.current,
    estimateSize: (i) => estimate(items[i] as T),
    overscan: 6,
  });
  return (
    <div ref={scroller} role="list" aria-label={label} className="h-[280px] overflow-auto">
      <div className="relative w-full" style={{ height: v.getTotalSize() }}>
        {v.getVirtualItems().map((row) => (
          <div
            key={row.key}
            ref={v.measureElement}
            data-index={row.index}
            role="listitem"
            className="absolute top-0 left-0 w-full"
            style={{ transform: `translateY(${row.start}px)` }}
          >
            {render(items[row.index] as T, row.index)}
          </div>
        ))}
      </div>
    </div>
  );
}

export function SavedCopies() {
  const { view } = useSavesOps();
  const { words } = view;
  const [tab, setTab] = useState("library");
  return (
    <Tabs.Root value={tab} onValueChange={setTab} className="flex flex-col gap-3">
      <div className="flex items-center gap-4">
        <h2 className={sectionTitle}>{words.copies}</h2>
        <Tabs.List aria-label={words.copies} className="flex gap-1">
          {(["library", "backups"] as const).map((t) => (
            <Tabs.Trigger
              key={t}
              value={t}
              className="h-8 rounded-control px-3 text-body text-text-secondary hover:bg-fill-ghost-hover data-[state=active]:bg-smear-selected data-[state=active]:text-text-primary"
            >
              {words[t]}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
      </div>
      <Tabs.Content value="library">
        <Library />
      </Tabs.Content>
      <Tabs.Content value="backups">
        <Backups />
      </Tabs.Content>
    </Tabs.Root>
  );
}

function Library() {
  const ops = useSavesOps();
  const { words, running, library_rows: rows, library_problems: problems } = ops.view;
  const spot = useDropSpot({ type: "library" });
  const [open, setOpen] = useState<Record<string, boolean>>({}); // kept by id: a recycled row stays open
  return (
    <div className="flex flex-col gap-3">
      {problems.map((p) => (
        <InfoBar key={p} severity="warning">
          {p}
        </InfoBar>
      ))}
      <Card aria-label={words.library} className={spot.className} {...spot.props}>
        {rows.length === 0 ? (
          <div className="flex flex-col gap-2 p-6">
            <p className="text-row text-text-primary">{words.noLibraryTitle}</p>
            <p className={hint}>{words.noLibrary}</p>
            <div>
              <Button disabled={running} onClick={ops.pickImport}>
                {words.importAction}
              </Button>
            </div>
          </div>
        ) : (
          <VirtualList
            items={rows}
            label={words.library ?? ""}
            estimate={(r) => 56 + (open[r.id] ? 40 * r.characters.length : 0)}
            render={(r) => (
              <LibraryItem row={r} expanded={!!open[r.id]} onToggle={() => setOpen((o) => ({ ...o, [r.id]: !o[r.id] }))} />
            )}
          />
        )}
        {rows.length > 0 ? (
          <div className="flex gap-2 px-4 py-3">
            <Button disabled={running} onClick={ops.pickImport}>
              {words.importAction}
            </Button>
            <Button onClick={() => ops.openFolder("library")}>{words.openFolder}</Button>
          </div>
        ) : null}
      </Card>
    </div>
  );
}

function LibraryItem({ row, expanded, onToggle }: { row: LibraryRow; expanded: boolean; onToggle: () => void }) {
  const ops = useSavesOps();
  const { words, running, cards, copy_targets } = ops.view;
  const Chevron = expanded ? ChevronDown : ChevronRight;
  return (
    <div>
      <div className="flex h-14 items-center gap-1 border-b border-border-hairline px-2">
        {!row.stranded && !running ? (
          <DragHandle source={{ type: "copy", folder: row.folder, id: row.id, missing: row.missing, label: row.name }} />
        ) : (
          <span className="size-6 shrink-0" />
        )}
        <button
          type="button"
          aria-expanded={expanded}
          onClick={onToggle}
          className="flex h-full min-w-0 flex-1 items-center gap-2 rounded-control px-1 text-left hover:bg-fill-ghost-hover"
        >
          <Chevron className="size-4 shrink-0 text-text-secondary" aria-hidden />
          <span className="flex min-w-0 flex-col">
            <span className="flex items-center gap-2">
              <span className="truncate text-row text-text-primary">{row.name}</span>
              <Pill>{row.tag}</Pill>
            </span>
            <span className={cn("truncate text-caption", row.note ? "text-status-warning" : "text-text-secondary")}>
              {row.note || `${row.who}  ·  ${row.when}`}
            </span>
          </span>
        </button>
        {row.stranded ? (
          <>
            <Button onClick={() => ops.finishStranded(row.folder, row.id, true)}>{words.putBack}</Button>
            <Button onClick={() => ops.finishStranded(row.folder, row.id, false)}>{words.finish}</Button>
          </>
        ) : (
          <>
            {row.missing ? (
              <IconButton aria-label={`${words.remove} ${row.name}`} title={words.remove} className="text-status-danger" onClick={() => ops.removeCopy(row.folder, row.id)}>
                <Trash2 className="size-4" aria-hidden />
              </IconButton>
            ) : null}
            <Menu label={`${words.copyActions} (${row.name})`}>
              {cards.map((c) => (
                <MenuItem key={c.path} disabled={running || row.missing} onSelect={() => ops.replaceFromLibrary(row.folder, row.id, c.path)}>
                  {(words.replaceKind ?? "").replace("{kind}", c.kind)}
                </MenuItem>
              ))}
              <MenuSeparator />
              <MenuItem onSelect={() => ops.askName({ mode: "rename", folder: row.folder, id: row.id, start: row.name })}>
                {words.rename}
              </MenuItem>
              <MenuItem danger onSelect={() => ops.removeCopy(row.folder, row.id)}>
                {words.remove}
              </MenuItem>
            </Menu>
          </>
        )}
      </div>
      {expanded
        ? row.characters.map((c) => {
            const source = { type: "copychar", folder: row.folder, id: row.id, slot: c.slot, label: `${c.name}  ·  ${c.levelText}` } as const;
            const usable = !running && !row.missing;
            return (
              <div key={c.slot} className="flex h-10 items-center gap-1 border-b border-border-hairline pr-2 pl-6">
                {usable ? <DragHandle source={source} /> : <span className="size-6 shrink-0" />}
                <button
                  type="button"
                  className="h-full min-w-0 flex-1 truncate rounded-control px-1 text-left text-row hover:bg-fill-ghost-hover"
                  onKeyDown={(e) => {
                    if ((e.ctrlKey || e.metaKey) && e.key === "c") {
                      ops.copyKey(source);
                      e.preventDefault();
                    }
                  }}
                >
                  {`${c.slot}  ·  ${c.name}  ·  ${c.levelText}`}
                </button>
                <Menu label={`${words.copyTo} (${c.name})`} disabled={!usable}>
                  {copy_targets.map((t) => (
                    <MenuItem
                      key={`${t.path}:${t.slot}`}
                      danger={t.danger}
                      onSelect={() => ops.copyFromLibrary(row.folder, row.id, c.slot, t.path, t.slot)}
                    >
                      {t.label}
                    </MenuItem>
                  ))}
                </Menu>
              </div>
            );
          })
        : null}
    </div>
  );
}

type Line = { day: string } | BackupRow;

function Backups() {
  const ops = useSavesOps();
  const { words, backup_days: days, retention } = ops.view;
  const spot = useDropSpot({ type: "backups" });
  const lines: Line[] = days.flatMap((d) => [{ day: d.day }, ...d.rows]);
  return (
    <Card aria-label={words.backups} className={spot.className} {...spot.props}>
      {lines.length === 0 ? (
        <p className={cn(hint, "p-4")}>{words.noBackups}</p>
      ) : (
        <VirtualList
          items={lines}
          label={words.backups ?? ""}
          estimate={(l) => ("day" in l ? 36 : 52)}
          render={(l) => ("day" in l ? <h3 className="px-4 pt-3 pb-1 text-caption text-text-secondary">{l.day}</h3> : <BackupItem row={l} />)}
        />
      )}
      <div className="flex items-center gap-3 px-4 py-3">
        <Button onClick={() => ops.openFolder("backups")}>{words.openFolder}</Button>
        <span className={hint}>{retention}</span>
      </div>
    </Card>
  );
}

function BackupItem({ row }: { row: BackupRow }) {
  const ops = useSavesOps();
  const { words, running, cards } = ops.view;
  const title = `${row.time}  ·  ${row.name}`;
  return (
    <div className="flex h-[52px] items-center gap-1 border-b border-border-hairline px-2">
      {!running ? <DragHandle source={{ type: "backup", path: row.path, label: title }} /> : <span className="size-6 shrink-0" />}
      <div className="flex min-w-0 flex-1 flex-col px-1">
        <span className="flex items-center gap-2">
          <span className="truncate text-row text-text-primary">{title}</span>
          {row.kept || row.unreadable ? <Pill level={row.unreadable ? "warning" : "accent"}>{words.kept}</Pill> : null}
        </span>
        <span className="truncate text-caption text-text-secondary">{`${row.trigger}  ·  ${row.size}`}</span>
      </div>
      <Menu label={`${words.copyActions} (${title})`}>
        {cards.map((c) => (
          <MenuItem key={c.path} disabled={running} onSelect={() => ops.restoreBackup(row.path, c.path)}>
            {(words.restoreKind ?? "").replace("{kind}", c.kind)}
          </MenuItem>
        ))}
        <MenuSeparator />
        <MenuItem onSelect={() => ops.askName({ mode: "keep", path: row.path, start: "" })}>{words.keep}</MenuItem>
        {row.kept ? <MenuItem onSelect={() => ops.letAgeOut(row.path)}>{words.letAgeOut}</MenuItem> : null}
        <MenuItem danger onSelect={() => ops.deleteBackup(row.path)}>
          {words.deleteAction}
        </MenuItem>
      </Menu>
    </div>
  );
}
