/**
 * A settings file's text as a form, for Mod Configs. The engine hands over raw text (mod_configs_open); this is a
 * TypeScript port of the reading half of the engine's adapters/formats/config_model.py. Writing stays with the
 * engine: it changes only the edited value's characters, so comments, order and unknown lines survive. What this file
 * adds on the writing side is `valueText`, which words a form value the way the file already spells it.
 */
import type { ConfigField, ConfigSection, ConfigValue } from '../../types';

/** Where a form field lives in the file, kept so a saved `section.key` can be sent back as (section, key). */
export interface FieldSpot { section: string; key: string; type: ConfigField['type']; raw: string }

export interface ParsedForm { sections: ConfigSection[]; spots: Map<string, FieldSpot> }

export type FormLang = 'ini' | 'toml';

export const langOf = (name: string): FormLang | undefined => {
  const ext = name.includes('.') ? name.slice(name.lastIndexOf('.') + 1).toLowerCase() : '';
  return ext === 'ini' || ext === 'cfg' || ext === 'conf' ? 'ini' : ext === 'toml' ? 'toml' : undefined;
};

const YES = ['1', 'true', 'on', 'yes'];
const PAIRS = [['1', '0'], ['true', 'false'], ['on', 'off'], ['yes', 'no']];
const SECTION = /^[ \t]*\[([^[\]]+)\][ \t]*(?:[;#].*)?$/;
const INI_LINE = /^([ \t]*)([A-Za-z0-9_][A-Za-z0-9_ .-]*?)([ \t]*[=:][ \t]*)(.*?)[ \t]*$/;
const DEFAULT = /\bdefault(?:\s+is|\s*[:=])\s*([^\s,;)]+)/i;

export const fieldKey = (section: string, key: string) => `${section}.${key}`;

interface Raw { section: string; key: string; value: string; desc: string; kind: string; choices?: [number, string][]; def?: string; readonly: boolean }

function defaultOf(desc: string): string | undefined {
  const m = DEFAULT.exec(desc);
  return m ? m[1]!.replace(/^["'.]+|["'.]+$/g, '') : undefined;
}

/** (kind, choices) from an INI comment: bool | choice | int | text | password. */
function iniKind(key: string, value: string, desc: string): { kind: string; choices?: [number, string][] } {
  const d = desc.replaceAll(' ', '').toUpperCase();
  if (key.toLowerCase() === 'cooppassword') return { kind: 'password' };
  if (d.includes('0=FALSE') && d.includes('1=TRUE')) return { kind: 'bool' };
  const choices = desc.includes('|') ? [...desc.matchAll(/(\d+)\s*=\s*([^|]+?)\s*(?=\||$)/g)].map((m): [number, string] => [Number(m[1]), m[2]!.trim().replace(/\.+$/, '')]) : [];
  if (choices.length >= 2) return { kind: 'choice', choices };
  const nums = [...desc.matchAll(/(-?\d+)\s*=/g)];
  if (desc.toUpperCase().includes('MAX') && nums.length >= 2) return { kind: 'int' };
  return /^\d+$/.test(value.trim().replace(/^-+/, '')) ? { kind: 'int' } : { kind: 'text' };
}

function parseIni(text: string): Raw[] {
  const out: Raw[] = [];
  const seen = new Map<string, Raw>();
  let section = '';
  let pending: string[] = [];
  for (const full of text.split('\n')) {
    const line = full.replace(/\r$/, '');
    const stripped = line.trim();
    if (!stripped) { pending = []; continue; }
    if (/^[;#]/.test(stripped)) { pending.push(stripped.replace(/^[;# ]+/, '').trim()); continue; }
    const sec = SECTION.exec(line);
    if (sec) { section = sec[1]!.trim(); pending = []; continue; }
    const desc = pending.join(' ');
    pending = [];
    const m = INI_LINE.exec(line);
    if (!m) continue;
    const key = m[2]!, value = m[4]!;
    const item: Raw = { section, key, value, desc, ...iniKind(key, value, desc), def: defaultOf(desc), readonly: false };
    // A key written twice can't be told apart on save: both stay read-only.
    const id = `${section.toLowerCase()}\n${key.toLowerCase()}`;
    const first = seen.get(id);
    if (first) { first.readonly = true; item.readonly = true; } else seen.set(id, item);
    out.push(item);
  }
  return out;
}

/* ------------------------------------------------------------------ TOML */
// shortcut: a line scanner, not a TOML parser. Tables, [[arrays of tables]] and one-line scalars become fields;
// arrays and multi-line values are read-only; inline tables and dotted keys are left to Edit as text. Upgrade to a
// TOML library if people need those from the form.

const BARE_KEY = /^([A-Za-z0-9_-]+)\s*=\s*(.*)$/;

function tomlValue(rest: string): { kind: string; value: string; readonly: boolean } | null {
  const v = rest.trim();
  if (v.startsWith('{')) return null;
  if (v.startsWith('"""') || v.startsWith("'''") || v.startsWith('[')) return { kind: 'text', value: v, readonly: true };
  const quote = v[0];
  if (quote === '"' || quote === "'") {
    const end = (quote === '"' ? /(?<!\\)"/ : /'/).exec(v.slice(1));
    if (!end) return { kind: 'text', value: v, readonly: true };
    const inner = v.slice(1, 1 + end.index);
    const escaped = quote === '"' && /\\(?!["\\])/.test(inner);
    return { kind: 'text', value: quote === '"' ? inner.replace(/\\(["\\])/g, '$1') : inner, readonly: escaped };
  }
  const bare = v.replace(/\s+#.*$/, '').trim();
  if (bare === 'true' || bare === 'false') return { kind: 'bool', value: bare, readonly: false };
  if (/^[+-]?\d[\d_]*$/.test(bare)) return { kind: 'int', value: bare, readonly: false };
  if (/^[+-]?(\d[\d_]*(\.\d[\d_]*)?([eE][+-]?\d+)?|inf|nan)$/.test(bare)) return { kind: 'float', value: bare, readonly: false };
  return { kind: 'text', value: bare, readonly: true }; // dates, times
}

function parseToml(text: string): Raw[] {
  const out: Raw[] = [];
  let section = '';
  let aot = { name: '', n: 0 };
  let pending: string[] = [];
  let closer = ''; // inside a multi-line string or array: the lines up to this are not settings
  for (const full of text.split('\n')) {
    const line = full.replace(/\r$/, '');
    const stripped = line.trim();
    if (closer) { if (stripped.includes(closer)) closer = ''; continue; }
    if (!stripped) { pending = []; continue; }
    if (stripped.startsWith('#')) { pending.push(stripped.replace(/^#+/, '').trim()); continue; }
    const desc = pending.join(' ');
    pending = [];
    const head = /^\[\[\s*([^\]]+?)\s*\]\]/.exec(stripped);
    if (head) { aot = { name: head[1]!, n: aot.name === head[1] ? aot.n + 1 : 1 }; section = `[[${aot.name}]] #${aot.n}`; continue; }
    const table = /^\[\s*([^[\]]+?)\s*\]/.exec(stripped);
    if (table) {
      const path = table[1]!;
      const inside = aot.name !== '' && path.startsWith(`${aot.name}.`);
      section = inside ? `[[${aot.name}]] #${aot.n}.${path.slice(aot.name.length + 1)}` : path;
      if (!inside) aot = { name: '', n: 0 };
      continue;
    }
    const m = BARE_KEY.exec(stripped);
    if (!m) continue;
    const rest = m[2]!.trim();
    const v = tomlValue(rest);
    if (!v) continue;
    const start = rest.slice(0, 3);
    if ((start === '"""' || start === "'''") && !rest.slice(3).includes(start)) closer = start;
    else if (rest.startsWith('[') && !rest.includes(']')) closer = ']';
    out.push({ section, key: m[1]!, value: v.value, desc, kind: v.kind, def: defaultOf(desc), readonly: v.readonly });
  }
  return out;
}

/* ------------------------------------------------------------------ the form */

function typed(r: Raw): { value: ConfigValue; type: ConfigField['type'] } {
  if (r.readonly) return { value: r.value, type: 'readonly' };
  switch (r.kind) {
    case 'bool': return { value: YES.includes(r.value.trim().toLowerCase()), type: 'bool' };
    case 'int': case 'float': {
      const n = Number(r.value.replaceAll('_', ''));
      return Number.isFinite(n) ? { value: n, type: r.kind } : { value: r.value, type: 'readonly' };
    }
    case 'choice': return { value: r.value.trim(), type: 'enum' };
    case 'password': return { value: r.value, type: 'secret' };
    default: return { value: r.value, type: 'string' };
  }
}

function defaultValue(r: Raw, type: ConfigField['type']): ConfigValue | undefined {
  if (r.def === undefined || type === 'readonly') return undefined;
  if (type === 'bool') return YES.includes(r.def.toLowerCase());
  if (type === 'int' || type === 'float') { const n = Number(r.def); return Number.isFinite(n) ? n : undefined; }
  return r.def;
}

/** The form of a settings file's text, or null when it reads as no settings (it is then edited as text). */
export function parseForm(lang: FormLang, text: string): ParsedForm | null {
  const sections = new Map<string, ConfigSection>();
  const spots = new Map<string, FieldSpot>();
  for (const r of lang === 'toml' ? parseToml(text) : parseIni(text)) {
    const { value, type } = typed(r);
    const field: ConfigField = { key: r.key, type, value };
    if (r.desc) field.help = r.desc;
    const def = defaultValue(r, type);
    if (def !== undefined) field.default = def;
    if (type === 'enum') {
      field.options = (r.choices ?? []).map(([n, label]) => ({ value: String(n), label }));
      if (!field.options.some((o) => o.value === value)) field.options.push({ value: String(value), label: String(value) }); // a value the comment doesn't list stays choosable
    }
    let s = sections.get(r.section);
    if (!s) { s = { name: r.section, fields: [] }; sections.set(r.section, s); }
    s.fields.push(field);
    spots.set(fieldKey(r.section, r.key), { section: r.section, key: r.key, type, raw: r.value });
  }
  return sections.size ? { sections: [...sections.values()], spots } : null;
}

/** A form value as the text to write: a switch keeps the file's own spelling (1/0, true/false, on/off, yes/no, in its case). */
export function valueText(spot: FieldSpot, value: ConfigValue): string {
  if (spot.type !== 'bool' || typeof value !== 'boolean') return String(value);
  const was = spot.raw.trim();
  const pair = PAIRS.find((p) => p.includes(was.toLowerCase())) ?? PAIRS[1]!;
  const word = pair[value ? 0 : 1]!;
  if (was === was.toUpperCase() && /[A-Z]/.test(was)) return word.toUpperCase();
  return /^[A-Z]/.test(was) ? word[0]!.toUpperCase() + word.slice(1) : word;
}
