import { useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import type { ConfigField, ConfigValue } from '@/api';
import { Input, Select, Switch } from '@/components/bayle/controls';
import { Tag } from '@/components/bayle/badge';
import { Button, LinkButton } from '@/components/ui/button';
import { cn } from '@/lib/utils';

const show = (v: ConfigValue | undefined) => (v === undefined ? '' : typeof v === 'boolean' ? (v ? 'on' : 'off') : v === '' ? 'empty' : String(v));

function Control({ field, value, onChange, id, invalid }: { field: ConfigField; value: ConfigValue; onChange: (v: ConfigValue) => void; id: string; invalid: boolean }) {
  const [reveal, setReveal] = useState(false);
  switch (field.type) {
    case 'bool':
      return <Switch id={id} checked={value === true} onCheckedChange={onChange} aria-label={field.key} />;
    case 'int':
    case 'float':
      return (
        <label className={cn('inline-flex items-center overflow-hidden rounded-sm border border-line2 bg-input focus-within:border-[var(--focus)]', invalid && 'border-bad focus-within:border-bad')}>
          {/* Text, not type=number: the form keeps what was typed and Zod says what's wrong with it. */}
          <input id={id} inputMode={field.type === 'float' ? 'decimal' : 'numeric'} value={String(value)} aria-label={field.key} aria-invalid={invalid}
            onChange={(e) => onChange(e.target.value)}
            className="h-[30px] w-24 bg-transparent px-2 text-right tabular-nums text-t1 outline-hidden" />
          {field.unit && <span className="pr-2.5 pl-1 text-xs text-t3">{field.unit}</span>}
        </label>
      );
    case 'secret':
      return (
        <span className="flex items-center gap-1.5">
          <Input id={id} className="w-[200px] font-mono" type={reveal ? 'text' : 'password'} value={String(value)} onChange={(e) => onChange(e.target.value)} aria-label={field.key} />
          <Button size="sm" variant="ghost" icon={reveal ? <EyeOff /> : <Eye />} onClick={() => setReveal(!reveal)} aria-pressed={reveal}>{reveal ? 'Hide' : 'Show'}</Button>
        </span>
      );
    case 'enum':
      return (
        <Select id={id} className="min-w-[180px]" value={String(value)} onChange={(e) => onChange(e.target.value)} aria-label={field.key}>
          {field.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </Select>
      );
    case 'readonly':
      return <span className="font-mono text-ui text-t2">{field.key} = {String(value)}</span>;
    default:
      return <Input id={id} className="w-[220px] font-mono" value={String(value)} onChange={(e) => onChange(e.target.value)} aria-label={field.key} />;
  }
}

/** One setting: name and help on the left, its control on the right, default or Changed + Reset under the name. */
export function FieldRow({ section, field, value, edited, error, onChange }: { section: string; field: ConfigField; value: ConfigValue; edited: boolean; error?: string; onChange: (v: ConfigValue) => void }) {
  const id = `cfg-${section}-${field.key}`;
  const differs = field.default !== undefined && String(value) !== String(field.default);
  return (
    <div className={cn('grid grid-cols-[minmax(0,1fr)_auto] items-start gap-6 max-[560px]:grid-cols-1 max-[560px]:gap-2.5 border-b border-line py-3 last:border-b-0', edited && 'shadow-[inset_2px_0_0_var(--accent)] -ml-4 pl-4')}>
      <div className="min-w-0">
        <label htmlFor={id} className="font-mono text-body font-medium text-t1">{field.key}</label>
        {(field.help || field.type === 'readonly') && <p className="m-0 mt-0.5 text-xs text-t3">{field.type === 'readonly' ? 'Only Edit as text can change this one.' : field.help}</p>}
        <div className="mt-1 flex items-center gap-2 text-caption text-t4">
          {differs ? (
            <>
              <Tag tone="accent">Changed</Tag>
              <LinkButton className="text-caption" onClick={() => onChange(field.default!)} title={`Back to the default: ${show(field.default)}`}>Reset</LinkButton>
              <span>Default: {show(field.default)}</span>
            </>
          ) : field.default !== undefined && field.type !== 'readonly' ? <span>Default: {show(field.default)}</span> : null}
        </div>
      </div>
      <div className="flex flex-col items-end gap-1 pt-0.5">
        <Control field={field} value={value} onChange={onChange} id={id} invalid={!!error} />
        {error && <p role="alert" className="m-0 text-xs text-bad">{error}</p>}
      </div>
    </div>
  );
}
