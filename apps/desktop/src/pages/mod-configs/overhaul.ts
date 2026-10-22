import type { FormValues } from "./types";

/** services.mod_configs.patch_values / basic.encode_action: the Overhaul setup form's edits, applied to a copy of the working values. */
export function encodeAction(action: string, target = ""): string {
  return action === "place" ? `place:${target}` : action;
}

export function decodeAction(value: string): [string, string] {
  return value.startsWith("place:") ? ["place", value.slice(6)] : [value, ""];
}

/** The page's "kind:name" row key. */
export function splitKey(key: string): [string, string] {
  const i = key.indexOf(":");
  return i < 0 ? [key, ""] : [key.slice(0, i), key.slice(i + 1)];
}

/** A new copy with the edit; the same values when the key names nothing there. */
export function patchValues(values: FormValues, key: string, value: string): FormValues {
  const [kind, name] = splitKey(key);
  const next: FormValues = {
    ...values,
    natives: values.natives.map((n) => ({ ...n })),
    files: { ...values.files },
    tables: { ...values.tables },
    health: { ...values.health },
  };
  const native = next.natives.find((n) => n.file === name);
  switch (kind) {
    case "early":
      if (!native) return values;
      native.load_early = value === "true";
      return next;
    case "after":
      if (!native) return values;
      native.after_others = value === "true";
      return next;
    case "init":
      if (!native) return values;
      native.initializer = value.trim() || null;
      return next;
    case "file":
      next.files[name] = encodeAction(value, decodeAction(values.files[name] ?? "")[1]);
      return next;
    case "target":
      next.files[name] = encodeAction("place", value.trim());
      return next;
    case "table":
      next.tables[name] = value;
      return next;
    case "health":
      if (!(name in values.health)) return values;
      next.health[name] = value;
      next.health_touched = true;
      return next;
    default:
      return values;
  }
}

/** What a form row shows for the working values (the row's own value is only the starting one). */
export function shownValue(values: FormValues, key: string, fallback: string): string {
  const [kind, name] = splitKey(key);
  const native = values.natives.find((n) => n.file === name);
  switch (kind) {
    case "early":
      return native ? String(!!native.load_early) : fallback;
    case "after":
      return native ? String(!!native.after_others) : fallback;
    case "init":
      return native ? (native.initializer ?? "") : fallback;
    case "file":
      return decodeAction(values.files[name] ?? "")[0];
    case "target":
      return decodeAction(values.files[name] ?? "")[1];
    case "table":
      return values.tables[name] ?? fallback;
    case "health":
      return values.health[name] ?? fallback;
    default:
      return fallback;
  }
}

/** The form as the operations take it (the log check only when it was touched). */
export function formOf(values: FormValues) {
  return {
    natives: values.natives,
    files: values.files,
    tables: values.tables,
    health: values.health_touched ? values.health : null,
  };
}
