import { useMemo } from 'react';
import { useForm, useWatch, type Resolver } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import type { ConfigField, ConfigFile, ConfigValue } from '@/api';

export const fieldKey = (section: string, key: string) => `${section}.${key}`;

export const isMarkdown = (f: ConfigFile) => f.format === 'markdown';

/** Text formats Bayle cannot show as a form open straight in text mode. */
export const isTextOnly = (f: ConfigFile) => !f.sections?.length;

export interface ConfigDraft {
  /** Current value of a field, edited or not. Numbers may be mid-typing text. */
  value: (section: string, field: ConfigField) => ConfigValue;
  setValue: (section: string, key: string, v: ConfigValue) => void;
  /** Field edited in this session but not saved. */
  isEdited: (section: string, field: ConfigField) => boolean;
  /** Why the field's value can't be saved, if it can't. */
  error: (section: string, field: ConfigField) => string | undefined;
  text: string;
  setText: (t: string) => void;
  textEdited: boolean;
  /** Unsaved changes: edited fields, plus one for edited text. */
  count: number;
  /** Every edited value passes its field's rules. */
  valid: boolean;
  discard: () => void;
  /** What to send to saveConfigFile. Text wins when it was edited. Null when nothing changed or a value is invalid. */
  change: () => { values: Record<string, ConfigValue> } | { text: string } | null;
}

/** Zod rule for one field's value, from its declared type. Numbers arrive as typed text and leave as numbers. */
function fieldSchema(f: ConfigField): z.ZodType<ConfigValue, unknown> {
  switch (f.type) {
    case 'bool': return z.boolean();
    case 'int': return z.coerce.string().trim().regex(/^-?\d+$/, 'A whole number.').transform(Number);
    case 'float': return z.coerce.string().trim().regex(/^-?(\d+\.?\d*|\.\d+)$/, 'A number, like 1.5.').transform(Number);
    case 'enum': return f.options?.length ? z.enum(f.options.map((o) => o.value) as [string, ...string[]], 'Pick one of the listed values.') : z.string();
    case 'string': case 'secret': return z.string();
    // Read-only values are never edited here; pass them through as they are.
    default: return z.union([z.string(), z.number(), z.boolean()]);
  }
}

type Values = { f: Record<string, ConfigValue>; text: string };

/**
 * Unsaved edits to one config file, held in React Hook Form and validated
 * with a Zod schema built from the file's fields. Field keys contain dots,
 * so the form stores them under index names (f.0, f.1, …).
 */
export function useConfigDraft(file: ConfigFile | undefined): ConfigDraft {
  const { names, fields, defaults, schema } = useMemo(() => {
    const names = new Map<string, string>();
    const fields = new Map<string, ConfigField>();
    const values: Record<string, ConfigValue> = {};
    const shape: Record<string, z.ZodType<ConfigValue, unknown>> = {};
    file?.sections?.forEach((s) => s.fields.forEach((f) => {
      const n = String(names.size);
      names.set(fieldKey(s.name, f.key), n);
      fields.set(n, f);
      values[n] = f.value;
      shape[n] = fieldSchema(f);
    }));
    return { names, fields, defaults: { f: values, text: file?.text ?? '' }, schema: z.object({ f: z.object(shape), text: z.string() }) };
  }, [file]);

  // `values` resets the form whenever another (or a reloaded) file arrives.
  const form = useForm<Values, unknown, z.output<typeof schema>>({ resolver: zodResolver(schema) as Resolver<Values, unknown, z.output<typeof schema>>, values: defaults, mode: 'onChange' });
  const current = useWatch({ control: form.control }) as Values;
  const { errors } = form.formState;

  const edited = (n: string) => String(current.f?.[n]) !== String(defaults.f[n]);
  const editedNames = [...fields.keys()].filter(edited);
  const textEdited = (current.text ?? defaults.text) !== defaults.text;
  const nameOf = (section: string, key: string) => names.get(fieldKey(section, key)) ?? '';
  const valid = editedNames.every((n) => !errors.f?.[n]);

  return {
    value: (section, field) => current.f?.[nameOf(section, field.key)] ?? field.value,
    setValue: (section, key, v) => form.setValue(`f.${nameOf(section, key)}`, v, { shouldDirty: true, shouldValidate: true }),
    isEdited: (section, field) => edited(nameOf(section, field.key)),
    error: (section, field) => errors.f?.[nameOf(section, field.key)]?.message,
    text: current.text ?? defaults.text,
    setText: (t) => form.setValue('text', t, { shouldDirty: true }),
    textEdited,
    count: editedNames.length + (textEdited ? 1 : 0),
    valid,
    discard: () => form.reset(defaults),
    change: () => {
      if (textEdited) return { text: form.getValues('text') };
      // Only edited fields are sent, so only they are parsed (numbers leave as numbers).
      const out: Record<string, ConfigValue> = {};
      for (const [key, n] of names) {
        if (!editedNames.includes(n)) continue;
        const r = fieldSchema(fields.get(n)!).safeParse(form.getValues(`f.${n}`));
        if (!r.success) return null;
        out[key] = r.data;
      }
      return editedNames.length ? { values: out } : null;
    },
  };
}
