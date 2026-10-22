import { GripVertical } from "lucide-react";
import { createContext, use, useCallback, useEffect, useRef, useState, type PointerEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/cn";
import { useSavesOps } from "./ops";
import type { DragSource, DropTarget } from "./types";

/**
 * Pointer-based drag and drop, like the Qt page's DragHandle (not the HTML5 one: the Tauri window keeps its own
 * file-drop handler, which the HTML5 events would fight). A handle starts a drag, the spots under the pointer carry
 * data-drop, and the backend (`saves.drop`, the presenter's one rule set) says what a drop means or why not. The same
 * actions are in the menus and on Ctrl+C / Ctrl+V, so no drag is needed.
 */
interface Active {
  source: DragSource;
  x: number;
  y: number;
  target: DropTarget | null;
  verdict: { ok: boolean; reason: string } | null;
}

const DragContext = createContext<{ start: (e: PointerEvent, source: DragSource) => void; active: Active | null } | null>(
  null,
);

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

function targetAt(x: number, y: number): DropTarget | null {
  for (const el of document.elementsFromPoint?.(x, y) ?? []) {
    const raw = el.closest("[data-drop]")?.getAttribute("data-drop");
    if (raw) return JSON.parse(raw) as DropTarget;
  }
  return null;
}

export function DragProvider({ children }: { children: ReactNode }) {
  const ops = useSavesOps();
  const opsRef = useRef(ops);
  useEffect(() => {
    opsRef.current = ops;
  });
  const [active, setActive] = useState<Active | null>(null);
  const cancel = useRef<(() => void) | null>(null);
  useEffect(() => () => cancel.current?.(), []);

  const start = useCallback((e: PointerEvent, source: DragSource) => {
    if (e.button !== 0) return;
    const [sx, sy] = [e.clientX, e.clientY];
    let began = false;
    let target: DropTarget | null = null;
    let seq = 0;

    const move = (ev: globalThis.PointerEvent) => {
      if (!began && Math.hypot(ev.clientX - sx, ev.clientY - sy) < 6) return;
      began = true;
      const t = targetAt(ev.clientX, ev.clientY);
      const unchanged = same(t, target);
      target = t;
      setActive((a) => ({ source, x: ev.clientX, y: ev.clientY, target: t, verdict: unchanged ? (a?.verdict ?? null) : null }));
      if (t && !unchanged) {
        const mine = ++seq;
        opsRef.current
          .judge(source, t)
          .then((d) => mine === seq && setActive((a) => (a ? { ...a, verdict: { ok: !d.reason, reason: d.reason } } : a)))
          .catch(() => undefined);
      }
    };
    const finish = (drop: boolean) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", abort);
      window.removeEventListener("keydown", key);
      cancel.current = null;
      setActive(null);
      if (began && drop && target) opsRef.current.drop(source, target);
    };
    const up = () => finish(true);
    const abort = () => finish(false);
    const key = (ev: KeyboardEvent) => ev.key === "Escape" && finish(false);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", abort);
    window.addEventListener("keydown", key);
    cancel.current = abort;
  }, []);

  return (
    <DragContext value={{ start, active }}>
      {children}
      {active
        ? createPortal(
            <div
              aria-hidden
              className="pointer-events-none fixed z-50 max-w-72 rounded-control border border-gold-line bg-surface-card px-3 py-1.5 text-body shadow-xl"
              style={{ left: active.x + 14, top: active.y + 14 }}
            >
              <div>{active.source.label}</div>
              {active.verdict && !active.verdict.ok ? <div className="text-caption text-status-danger">{active.verdict.reason}</div> : null}
            </div>,
            document.body,
          )
        : null}
    </DragContext>
  );
}

const useDrag = () => {
  const ctx = use(DragContext);
  if (!ctx) throw new Error("useDrag outside DragProvider");
  return ctx;
};

/** The grip that starts a drag. Pointer only: the menus and Ctrl+C / Ctrl+V do the same without it. */
export function DragHandle({ source, className }: { source: DragSource; className?: string }) {
  const { start } = useDrag();
  return (
    <span
      aria-hidden
      title={source.label}
      className={cn("inline-flex size-6 shrink-0 cursor-grab touch-none items-center justify-center text-text-tertiary select-none hover:text-text-primary", className)}
      onPointerDown={(e) => start(e, source)}
    >
      <GripVertical className="size-4" />
    </span>
  );
}

/** Props for a spot a drag can land on, and how to show it: "ok" takes the drop, "no" refuses it, "" is not hovered. */
export function useDropSpot(target: DropTarget): { props: { "data-drop": string }; state: "" | "ok" | "no" | "wait"; className: string } {
  const { active } = useDrag();
  const hot = active?.target && same(active.target, target) ? active : null;
  const state = !hot ? "" : !hot.verdict ? "wait" : hot.verdict.ok ? "ok" : "no";
  return {
    props: { "data-drop": JSON.stringify(target) },
    state,
    className: state === "ok" ? "ring-2 ring-accent" : state === "no" ? "ring-2 ring-status-danger" : state === "wait" ? "ring-1 ring-border-edge" : "",
  };
}
