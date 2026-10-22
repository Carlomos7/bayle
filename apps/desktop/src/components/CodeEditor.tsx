import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { json } from "@codemirror/lang-json";
import { markdown } from "@codemirror/lang-markdown";
import { HighlightStyle, StreamLanguage, syntaxHighlighting } from "@codemirror/language";
import { lua } from "@codemirror/legacy-modes/mode/lua";
import { properties } from "@codemirror/legacy-modes/mode/properties";
import { toml } from "@codemirror/legacy-modes/mode/toml";
import { lintGutter, setDiagnostics } from "@codemirror/lint";
import { search, searchKeymap } from "@codemirror/search";
import { Compartment, EditorState, type Extension } from "@codemirror/state";
import { EditorView, drawSelection, highlightActiveLine, keymap, lineNumbers } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";

const LANGUAGES: Record<string, string> = {
  me3: "toml",
  toml: "toml",
  ini: "ini",
  cfg: "ini",
  conf: "ini",
  json: "json",
  hks: "lua",
  lua: "lua",
  md: "markdown",
  markdown: "markdown",
};

/** The editor's language by file name, as the Qt editor picks it by extension. */
export function languageFor(name: string): string {
  return LANGUAGES[name.toLowerCase().split(".").pop() ?? ""] ?? "";
}

function support(language: string): Extension {
  switch (language) {
    case "toml":
      return StreamLanguage.define(toml);
    case "ini":
      return StreamLanguage.define(properties);
    case "lua":
      return StreamLanguage.define(lua);
    case "json":
      return json();
    case "markdown":
      return markdown();
    default:
      return [];
  }
}

// Colours come from the theme tokens, so dark, light and Tarnished all follow.
const colours = HighlightStyle.define([
  { tag: [tags.keyword, tags.atom, tags.bool], color: "var(--syntax-keyword)" },
  { tag: [tags.string, tags.special(tags.string)], color: "var(--syntax-string)" },
  { tag: [tags.number, tags.integer, tags.float], color: "var(--syntax-number)" },
  { tag: [tags.comment, tags.lineComment, tags.blockComment], color: "var(--syntax-comment)", fontStyle: "italic" },
  { tag: [tags.propertyName, tags.attributeName, tags.definition(tags.propertyName)], color: "var(--syntax-key)" },
  { tag: [tags.heading, tags.labelName, tags.typeName, tags.namespace], color: "var(--syntax-header)", fontWeight: "600" },
]);

const theme = EditorView.theme({
  "&": { height: "100%", color: "var(--text-primary)", backgroundColor: "var(--surface-input)", fontSize: "13px" },
  ".cm-scroller": { fontFamily: "ui-monospace, 'Cascadia Mono', Consolas, monospace", lineHeight: "1.5" },
  ".cm-content": { caretColor: "var(--accent)" },
  "&.cm-focused": { outline: "none" },
  ".cm-gutters": { backgroundColor: "transparent", color: "var(--text-tertiary)", border: "none", borderRight: "1px solid var(--border-hairline)" },
  ".cm-activeLine": { backgroundColor: "var(--fill-hover)" },
  ".cm-activeLineGutter": { backgroundColor: "transparent", color: "var(--text-primary)" },
  ".cm-cursor": { borderLeftColor: "var(--accent)" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground": { backgroundColor: "var(--accent-soft)" },
  ".cm-panels": { backgroundColor: "var(--surface-card)", color: "var(--text-primary)", borderColor: "var(--border-edge)" },
  ".cm-panels input, .cm-panels button": { color: "inherit", font: "inherit" },
  ".cm-panels input": { backgroundColor: "var(--surface-input)", border: "1px solid var(--border-edge)", padding: "2px 6px", borderRadius: "3px" },
  ".cm-searchMatch": { backgroundColor: "var(--accent-soft)", outline: "1px solid var(--accent-glow)" },
  ".cm-lintRange-error": { backgroundImage: "none", textDecoration: "underline wavy var(--status-danger)" },
  ".cm-lint-marker-error": { content: "none", color: "var(--status-danger)" },
});

export interface EditorProblem {
  /** 1-based; 0 means no problem. */
  line: number;
  message: string;
}

export interface CodeEditorProps {
  value: string;
  onChange?: (text: string) => void;
  fileName: string;
  readOnly?: boolean;
  /** Parse check for TOML, INI and JSON text; runs 400 ms after typing stops. It never blocks saving. */
  check?: (text: string) => Promise<EditorProblem>;
  /** The editor's own words (the caller supplies them). */
  labels?: { wrap: string; lineColumn: (line: number, column: number) => string };
  className?: string;
  "aria-label"?: string;
}

const DEFAULT_LABELS = { wrap: "Wrap long lines", lineColumn: (l: number, c: number) => `Line ${l}, column ${c}` };

/**
 * The one text editor (CodeMirror 6): line numbers, syntax colours from the theme tokens, the current line, find and
 * replace (Ctrl+F, F3 / Shift+F3), go to line (Ctrl+G), Tab to indent, wrap (Alt+Z), and the first parse error marked
 * on its line with its words under the editor.
 */
export function CodeEditor({ value, onChange, fileName, readOnly = false, check, labels = DEFAULT_LABELS, className, ...rest }: CodeEditorProps) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  const checkRef = useRef(check);
  const [wrap, setWrap] = useState(false);
  const [cursor, setCursor] = useState({ line: 1, column: 1 });
  const [problem, setProblem] = useState<EditorProblem>({ line: 0, message: "" });
  const wrapSlot = useRef(new Compartment());
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const generation = useRef(0);
  const label = rest["aria-label"] ?? fileName;
  useEffect(() => {
    onChangeRef.current = onChange;
    checkRef.current = check;
  });

  // Check now, or 400 ms after the last keystroke; a newer check supersedes an older answer.
  const runCheck = useCallback((text: string, now = false) => {
    clearTimeout(timer.current);
    if (!checkRef.current) return;
    const gen = ++generation.current;
    const go = () =>
      void checkRef.current?.(text).then(
        (p) => {
          const v = view.current;
          if (gen !== generation.current || !v) return;
          setProblem(p);
          const ok = p.line > 0 && p.line <= v.state.doc.lines;
          const at = ok ? v.state.doc.line(p.line) : null;
          v.dispatch(setDiagnostics(v.state, at ? [{ from: at.from, to: at.to, severity: "error", message: p.message }] : []));
        },
        () => {},
      );
    if (now) go();
    else timer.current = setTimeout(go, 400);
  }, []);

  useEffect(() => {
    const state = EditorState.create({
      doc: value,
      extensions: [
        lineNumbers(),
        history(),
        drawSelection(),
        highlightActiveLine(),
        search({ top: true }),
        lintGutter(),
        syntaxHighlighting(colours),
        support(languageFor(fileName)),
        theme,
        wrapSlot.current.of([]),
        EditorState.readOnly.of(readOnly),
        EditorView.editable.of(!readOnly),
        keymap.of([
          {
            key: "Alt-z",
            run: () => {
              setWrap((w) => !w);
              return true;
            },
          },
          indentWithTab,
          ...searchKeymap,
          ...historyKeymap,
          ...defaultKeymap,
        ]),
        EditorView.contentAttributes.of({ "aria-label": label, "aria-multiline": "true" }),
        EditorView.updateListener.of((u) => {
          if (u.docChanged) {
            const text = u.state.doc.toString();
            onChangeRef.current?.(text);
            runCheck(text);
          }
          if (u.selectionSet || u.docChanged) {
            const head = u.state.selection.main.head;
            const line = u.state.doc.lineAt(head);
            setCursor({ line: line.number, column: head - line.from + 1 });
          }
        }),
      ],
    });
    const v = new EditorView({ state, parent: host.current! });
    view.current = v;
    runCheck(value, true);
    return () => {
      clearTimeout(timer.current);
      v.destroy();
      view.current = null;
    };
    // The editor is rebuilt for a different file or mode, not on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileName, readOnly, label]);

  // A new text from outside (Reload, Discard) replaces the document; typing already matches it.
  useEffect(() => {
    const v = view.current;
    if (v && v.state.doc.toString() !== value) {
      v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: value } });
      runCheck(value, true);
    }
  }, [value, runCheck]);

  useEffect(() => {
    view.current?.dispatch({ effects: wrapSlot.current.reconfigure(wrap ? EditorView.lineWrapping : []) });
  }, [wrap]);

  return (
    <div
      className={cn(
        "flex min-h-80 flex-col overflow-hidden rounded-card border border-border-edge",
        problem.line > 0 && "border-status-danger",
        className,
      )}
    >
      <div ref={host} className="min-h-0 flex-1 overflow-hidden" />
      <div className="flex items-center gap-3 border-t border-border-hairline px-3 py-1 text-caption text-text-secondary">
        <span role={problem.line > 0 ? "alert" : undefined} className={cn("min-w-0 flex-1 truncate", problem.line > 0 && "text-status-danger")}>
          {problem.line > 0 ? problem.message : ""}
        </span>
        <span>{labels.lineColumn(cursor.line, cursor.column)}</span>
        <label className="flex items-center gap-1">
          <input type="checkbox" className="accent-accent" checked={wrap} onChange={(e) => setWrap(e.target.checked)} />
          {labels.wrap}
        </label>
      </div>
    </div>
  );
}
