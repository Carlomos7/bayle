import { useVirtualizer } from "@tanstack/react-virtual";
import { FileText, GripVertical, Pin, Settings, Trash2 } from "lucide-react";
import { ContextMenu, Switch } from "radix-ui";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { useMods } from "./context";
import type { DragTable, Group, Row } from "./types";
import { Card, Pill, menuItemClass } from "./ui";

export const ROW_H = 56;

interface Drag {
  entry: number; // the profile block index
  from: number; // 0-based among the kind as shown
  startY: number;
  startScroll: number;
  dy: number;
  to: number;
  table: DragTable | null; // the refusal for every drop spot, asked once when the drag begins
}

/** Where a row dropped dy pixels lower than it started lands, among n rows. */
export const dropTarget = (from: number, dy: number, n: number) => Math.max(0, Math.min(n - 1, from + Math.round(dy / ROW_H)));

/** A group on the Mods page (Packages, Natives (DLLs)): its title and count, its lines, then one card of rows. */
export function ModGroup({ group }: { group: Group }) {
  const { words, actions, openAddExisting } = useMods();
  const rows = group.rows;
  const scrollRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const dragRef = useRef<Drag | null>(null);
  const pointerY = useRef(0);
  const cancelled = useRef(false);
  const [focused, setFocused] = useState(0);
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtual = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_H,
    getItemKey: (i) => rows[i]?.index ?? i,
    overscan: 10,
  });

  const update = useCallback((next: Drag | null) => {
    dragRef.current = next;
    setDrag(next);
  }, []);

  // a lifted row near the top or bottom edge scrolls the list
  useEffect(() => {
    if (!drag) return;
    const timer = setInterval(() => {
      const el = scrollRef.current;
      const d = dragRef.current;
      if (!el || !d) return;
      const box = el.getBoundingClientRect();
      if (box.height === 0) return;
      const edge = 40;
      const step = pointerY.current < box.top + edge ? -14 : pointerY.current > box.bottom - edge ? 14 : 0;
      if (step) {
        el.scrollTop += step;
        const dy = pointerY.current - d.startY + (el.scrollTop - d.startScroll);
        update({ ...d, dy, to: dropTarget(d.from, dy, rows.length) });
      }
    }, 16);
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") {
        cancelled.current = true; // the drop does nothing
        update(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      clearInterval(timer);
      window.removeEventListener("keydown", onKey);
    };
  }, [drag === null, rows.length, update]); // eslint-disable-line react-hooks/exhaustive-deps

  const begin = (e: PointerEvent, row: Row, from: number) => {
    if (row.locked || e.button !== 0) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    cancelled.current = false;
    pointerY.current = e.clientY;
    const mine: Drag = { entry: row.index, from, startY: e.clientY, startScroll: scrollRef.current?.scrollTop ?? 0, dy: 0, to: from, table: null };
    update(mine);
    // one read; the spots are judged in memory as the pointer moves (the real check and the write happen on drop)
    actions.dragTable(row.index).then(
      (table) => dragRef.current?.entry === row.index && update({ ...dragRef.current, table }),
      () => {},
    );
  };
  const move = (e: PointerEvent) => {
    const d = dragRef.current;
    if (!d) return;
    pointerY.current = e.clientY;
    const dy = e.clientY - d.startY + ((scrollRef.current?.scrollTop ?? 0) - d.startScroll);
    update({ ...d, dy, to: dropTarget(d.from, dy, rows.length) });
  };
  const end = () => {
    const d = dragRef.current;
    update(null);
    // a refused drop still asks: the move says why in a toast (with Edit options) and puts the row back
    if (d && !cancelled.current && d.to !== d.from) actions.move(d.entry, d.to);
  };

  const onRowKey = (e: KeyboardEvent, i: number) => {
    const row = rows[i];
    if (!row) return;
    const to = e.key === "ArrowUp" ? i - 1 : e.key === "ArrowDown" ? i + 1 : null;
    if (to === null || e.target !== e.currentTarget) return;
    e.preventDefault();
    if (e.ctrlKey) {
      // the keyboard twin of the drag: Ctrl+Up / Ctrl+Down
      if (!row.locked && to >= 0 && to < rows.length) actions.move(row.index, to);
      return;
    }
    if (to < 0 || to >= rows.length) return;
    setFocused(to);
    virtual.scrollToIndex(to);
    requestAnimationFrame(() => scrollRef.current?.querySelector<HTMLElement>(`[data-pos="${to}"]`)?.focus());
  };
  const moveBy = (i: number, delta: number) => {
    const row = rows[i];
    const to = Math.max(0, Math.min(rows.length - 1, i + delta));
    if (row && to !== i) actions.move(row.index, to);
  };

  const reason = drag?.table?.reasons[drag.to] ?? "";
  const dropY = drag ? (drag.to > drag.from ? drag.to + 1 : drag.to) * ROW_H : 0;

  return (
    <section aria-label={group.title} className="flex flex-col gap-2">
      <div className="flex items-baseline gap-2">
        <h2 className="text-section font-semibold text-title">{group.title}</h2>
        <span className="text-caption text-text-tertiary">{group.count}</span>
      </div>
      {group.lines.map((line) => (
        <div key={`${line.index ?? -1}-${line.text}`} className="flex items-center gap-2">
          {(line.index ?? -1) >= 0 ? <Pill level="muted" icon="Info" text={words.loadsNothing ?? ""} /> : null}
          <span className="text-caption text-text-tertiary">{line.text}  ·</span>
          <button
            type="button"
            className="text-caption text-accent hover:underline"
            onClick={() => (line.index !== undefined && line.index >= 0 ? actions.removeHolder(line.index) : openAddExisting(group.kind))}
          >
            {line.action}
          </button>
        </div>
      ))}
      {group.empty ? <p className="text-caption text-text-tertiary">{group.empty}</p> : null}
      {rows.length > 0 ? (
        <Card className="overflow-hidden">
          <div ref={scrollRef} className="overflow-auto" style={{ maxHeight: `min(70vh, ${rows.length * ROW_H}px)` }}>
            <div role="list" aria-label={group.title} className="relative" style={{ height: virtual.getTotalSize() }}>
              {virtual.getVirtualItems().map((item) => {
                const row = rows[item.index];
                if (!row) return null;
                const held = drag?.entry === row.index;
                return (
                  <div
                    key={item.key}
                    role="listitem"
                    className="absolute inset-x-0 top-0"
                    style={{ height: ROW_H, transform: `translateY(${item.start}px)`, zIndex: held ? 10 : undefined }}
                  >
                    <ModRow
                      row={row}
                      pos={item.index}
                      last={item.index === rows.length - 1}
                      tabbable={focused === item.index}
                      held={held}
                      dy={held ? drag.dy : 0}
                      onKeyDown={(e) => onRowKey(e, item.index)}
                      onFocus={() => setFocused(item.index)}
                      onGrip={{ down: (e) => begin(e, row, item.index), move, up: end }}
                      moveBy={(d) => moveBy(item.index, d)}
                    />
                  </div>
                );
              })}
              {drag ? (
                <div aria-hidden className="pointer-events-none absolute inset-x-4 z-20" style={{ top: dropY - 1 }}>
                  <div className={cn("h-0.5", reason ? "bg-status-danger" : "bg-accent")} />
                  {reason ? <p className="absolute right-0 mt-1 rounded-card border border-status-danger bg-surface-card px-2 py-1 text-caption text-status-danger">{reason}</p> : null}
                </div>
              ) : null}
            </div>
          </div>
          {/* the reason is also said to screen readers while a row is lifted */}
          <p role="status" className="sr-only">
            {reason}
          </p>
        </Card>
      ) : null}
    </section>
  );
}

function ModRow({
  row,
  pos,
  last,
  tabbable,
  held,
  dy,
  onKeyDown,
  onFocus,
  onGrip,
  moveBy,
}: {
  row: Row;
  pos: number;
  last: boolean;
  tabbable: boolean;
  held: boolean;
  dy: number;
  onKeyDown(e: KeyboardEvent): void;
  onFocus(): void;
  onGrip: { down(e: PointerEvent): void; move(e: PointerEvent): void; up(e: PointerEvent): void };
  moveBy(delta: number): void;
}) {
  const { view, words, actions, openOptions, openRename, openConfigs } = useMods();
  const configs = view.configs[row.index] ?? [];
  const dim = row.enabled ? "" : "opacity-55";
  return (
    <ContextMenu.Root>
      <ContextMenu.Trigger asChild disabled={row.locked}>
        <div
          data-pos={pos}
          tabIndex={tabbable ? 0 : -1}
          aria-label={row.name}
          aria-keyshortcuts="Control+ArrowUp Control+ArrowDown"
          onKeyDown={onKeyDown}
          onFocus={onFocus}
          title={row.more || undefined}
          style={{ transform: held ? `translateY(${dy}px) scale(1.02)` : undefined }}
          className={cn(
            "relative flex h-full items-center gap-2 px-4 outline-offset-[-2px] hover:bg-fill-hover focus-visible:bg-accent-soft",
            held && "rounded-card bg-surface-card shadow-xl",
            !last && !held && "border-b border-border-hairline",
          )}
        >
          <button
            type="button"
            aria-label={`${row.name}: ${row.locked ? words.lockedTip : "drag to reorder, or Ctrl+Up and Ctrl+Down"}`}
            title={row.locked ? words.lockedTip : undefined}
            disabled={row.locked}
            onPointerDown={onGrip.down}
            onPointerMove={onGrip.move}
            onPointerUp={onGrip.up}
            onPointerCancel={onGrip.up}
            className={cn("grid size-8 shrink-0 touch-none place-items-center rounded-control text-text-icon", row.locked ? "text-text-disabled" : "cursor-grab active:cursor-grabbing")}
          >
            {row.locked ? <Pin aria-hidden className="size-4" /> : <GripVertical aria-hidden className="size-4" />}
          </button>
          <span className={cn("w-5 shrink-0 text-right text-caption tabular-nums text-text-secondary", dim)}>{row.position}</span>
          <Switch.Root
            checked={row.enabled}
            onCheckedChange={(on) => actions.setEnabled(row.index, on, row.name)}
            aria-label={row.name}
            className="relative h-5 w-9 shrink-0 rounded-pill border border-border-edge bg-surface-input data-[state=checked]:border-gold-line data-[state=checked]:bg-gold-fill-top"
          >
            <Switch.Thumb className="block size-3.5 translate-x-0.5 rounded-pill bg-text-primary transition-transform duration-toggle data-[state=checked]:translate-x-[18px] data-[state=checked]:bg-gold-text" />
          </Switch.Root>
          <div className={cn("flex min-w-0 flex-1 flex-col gap-0.5", dim)}>
            <div className="flex items-center gap-2">
              <span className="min-w-20 truncate text-row font-medium text-title">{row.name}</span>
              {row.tags.map((t) => (
                <Pill key={t.text} level={t.level} icon={t.icon} text={t.text} tip={t.tip} />
              ))}
            </div>
            {row.status ? <span className={cn("truncate text-caption", row.status_error ? "text-status-danger" : "text-text-secondary")}>{row.status}</span> : null}
          </div>
          <div className="flex shrink-0 items-center">
            <button
              type="button"
              aria-label={`${words.optionsTip}: ${row.name}`}
              title={words.optionsTip + (row.has_configs ? `  ·  ${words.configsTip}: ${row.configs_tip}` : "")}
              onClick={() => openOptions(row.index)}
              className="relative grid size-8 place-items-center rounded-control text-text-icon hover:bg-fill-ghost-hover"
            >
              <Settings aria-hidden className="size-4" />
              {row.has_configs ? <span aria-hidden className="absolute top-1 right-1 size-[7px] rounded-pill bg-accent" /> : null}
            </button>
            {row.kind === "native" ? (
              <button
                type="button"
                aria-label={`${words.attachTip}: ${row.name}`}
                title={words.attachTip}
                onClick={() => openConfigs(row.name)}
                className="grid size-8 place-items-center rounded-control text-text-icon hover:bg-fill-ghost-hover"
              >
                <FileText aria-hidden className="size-4" />
              </button>
            ) : null}
            <button
              type="button"
              aria-label={`${words.removeTip}: ${row.name}`}
              title={words.removeTip}
              onClick={() => actions.remove(row.index, row.name)}
              className="grid size-8 place-items-center rounded-control text-status-danger hover:bg-status-danger-bg"
            >
              <Trash2 aria-hidden className="size-4" />
            </button>
          </div>
          {configs.length > 0 ? <span className="sr-only">{configs.join(", ")}</span> : null}
        </div>
      </ContextMenu.Trigger>
      <ContextMenu.Portal>
        <ContextMenu.Content aria-label={row.name} className="z-50 min-w-52 rounded-overlay border border-border-edge bg-surface-card p-1 shadow-xl">
          <RowItem onSelect={() => moveBy(-1)} shortcut="Ctrl+Up">{words.moveUp}</RowItem>
          <RowItem onSelect={() => moveBy(1)} shortcut="Ctrl+Down">{words.moveDown}</RowItem>
          <RowItem onSelect={() => moveBy(-1000)}>{words.moveTop}</RowItem>
          <RowItem onSelect={() => moveBy(1000)}>{words.moveBottom}</RowItem>
          <RowItem onSelect={() => openRename(row.index)}>{words.rename}</RowItem>
          {row.kind === "package" && row.can_share ? <RowItem onSelect={() => actions.share(row.index)}>{words.share}</RowItem> : null}
          {row.kind === "package" && (row.shared ?? 0) > 0 ? (
            <>
              <RowItem onSelect={() => actions.useInOthers(row.index, row.name)}>{words.useInOthers}</RowItem>
              <RowItem onSelect={() => actions.separate(row.index)}>{words.useSeparate}</RowItem>
            </>
          ) : null}
        </ContextMenu.Content>
      </ContextMenu.Portal>
    </ContextMenu.Root>
  );
}

function RowItem({ children, onSelect, shortcut }: { children: ReactNode; onSelect(): void; shortcut?: string }) {
  return (
    <ContextMenu.Item className={cn(menuItemClass, "data-[highlighted]:bg-fill-hover")} onSelect={onSelect}>
      <span className="flex-1">{children}</span>
      {shortcut ? <kbd className="text-caption text-text-tertiary">{shortcut}</kbd> : null}
    </ContextMenu.Item>
  );
}
