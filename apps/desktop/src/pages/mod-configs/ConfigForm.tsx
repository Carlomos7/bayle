import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, Choice, FormRow, Spin, TextField, Toggle } from "./controls";
import type { Row, Section } from "./types";

export interface FormModel {
  sections: Section[];
  /** What a row shows now (its value on disk, or the waiting edit). */
  valueOf(row: Row): string;
  edited(row: Row): boolean;
  onChange(row: Row, value: string): void;
  onReset?(row: Row): void;
  words: Record<string, string>;
}

const matches = (r: Row, needle: string) =>
  needle === "" || `${r.label} ${r.key} ${r.blurb} ${r.help}`.toLowerCase().includes(needle);

/**
 * A settings file as a form: one card per section, one row per setting with the control its kind asks for. A big file
 * (more than 8 settings) gets Find (Ctrl+F). Every edit goes to the page, which keeps it until Save.
 */
export function ConfigForm({ model }: { model: FormModel }) {
  const { sections, words } = model;
  const total = sections.reduce((n, s) => n + s.rows.length, 0);
  const [typed, setTyped] = useState("");
  const [needle, setNeedle] = useState("");
  const find = useRef<HTMLInputElement>(null);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const id = setTimeout(() => setNeedle(typed.trim().toLowerCase()), 200);
    return () => clearTimeout(id);
  }, [typed]);

  useEffect(() => {
    if (total <= 8) return;
    const on = (e: KeyboardEvent) => {
      if (e.ctrlKey && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "f" && root.current?.offsetParent !== null) {
        e.preventDefault();
        find.current?.focus();
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [total]);

  const count = useMemo(() => sections.reduce((n, s) => n + s.rows.filter((r) => matches(r, needle)).length, 0), [sections, needle]);

  return (
    <div ref={root} className="flex flex-col gap-4">
      {total > 8 ? (
        <div className="flex items-center gap-2">
          <input
            ref={find}
            type="search"
            aria-label={words.findSetting}
            placeholder={words.findSetting}
            className="h-[var(--control-h)] w-64 rounded-control border border-border-edge bg-surface-input px-2 text-body outline-none focus-visible:border-accent"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && setTyped("")}
          />
          <span role="status" className="text-caption text-text-secondary">
            {needle === "" ? "" : count === 0 ? words.noMatch : (words.matchCount ?? "").replace("{n}", String(count))}
          </span>
        </div>
      ) : null}
      {sections.map((s, i) => {
        const rows = s.rows.filter((r) => matches(r, needle));
        if (rows.length === 0) return null;
        return (
          <section key={`${s.path ?? s.title}-${i}`} className="flex flex-col gap-2" aria-label={s.title || undefined}>
            {s.title ? (
              <h3 title={s.path && s.path !== s.title ? s.path : undefined} className="font-semibold text-body text-text-primary">
                {s.title}
              </h3>
            ) : null}
            <Card>
              {rows.map((r, k) => (
                <SettingRow key={`${r.section}|${r.key}`} row={r} model={model} divider={k < rows.length - 1} />
              ))}
            </Card>
          </section>
        );
      })}
    </div>
  );
}

function SettingRow({ row, model, divider }: { row: Row; model: FormModel; divider: boolean }) {
  const { words } = model;
  const current = model.valueOf(row);
  const edited = model.edited(row);
  const change = (v: string) => model.onChange(row, v);
  const help = row.blurb !== "" ? row.blurb : row.help;
  return (
    <FormRow title={row.label} help={help} divider={divider} testId={`setting_${row.key}`}>
      {(id) => (
        <>
          {edited ? (
            <span className="text-caption text-accent" aria-label={words.changed}>
              ● {words.changed}
            </span>
          ) : null}
          {row.kind === "bool" ? <Toggle id={id} checked={current === row.onValue} onChange={(on) => change(on ? row.onValue : row.offValue)} /> : null}
          {row.kind === "choice" ? <Choice id={id} value={current} choices={row.choices} onChange={change} /> : null}
          {row.kind === "int" ? <Spin id={id} value={Number.parseInt(current, 10) || 0} lo={row.lo} hi={row.hi} onChange={(n) => change(String(n))} /> : null}
          {row.kind === "text" || row.kind === "float" || row.kind === "password" ? (
            <TextField id={id} type={row.kind === "password" ? "password" : "text"} value={current} onChange={change} />
          ) : null}
          {row.kind === "readonly" ? <span id={id} className="text-caption text-text-secondary">{words.readonly}</span> : null}
          {row.tip !== "" && row.kind !== "readonly" && model.onReset ? (
            <Button className="h-7 min-w-0 px-2 text-caption" title={row.tip} onClick={() => model.onReset?.(row)}>
              {words.reset}
            </Button>
          ) : null}
        </>
      )}
    </FormRow>
  );
}
