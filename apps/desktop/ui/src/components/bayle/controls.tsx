import { useRef, type InputHTMLAttributes, type ReactNode, type Ref } from 'react';
import { Search } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Switch as UiSwitch } from '@/components/ui/switch';
import { Checkbox as UiCheckbox } from '@/components/ui/checkbox';
import { Input, fieldClass } from '@/components/ui/input';
import { NativeSelect } from '@/components/ui/native-select';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Kbd } from './badge';

/** Field look shared with shadcn's Input. */
// eslint-disable-next-line react-refresh/only-export-components -- shared field class
export const inputClass = fieldClass;
export { Input };
/** Native select (cheap in long lists). For a few options, shadcn's Select also fits. */
export const Select = NativeSelect;

/* ------------------------------------------------------------------ switch */

export interface SwitchProps {
  checked: boolean;
  onCheckedChange: (on: boolean) => void;
  disabled?: boolean;
  size?: 'sm' | 'md';
  'aria-label'?: string;
  title?: string;
  id?: string;
}

export function Switch(props: SwitchProps) {
  return <UiSwitch {...props} />;
}

/* ------------------------------------------------------------------ checkbox */

export interface CheckboxProps {
  checked: boolean | 'indeterminate';
  /** Gets shiftKey so lists can select a range. */
  onCheckedChange: (on: boolean, e?: { shiftKey: boolean }) => void;
  disabled?: boolean;
  'aria-label'?: string;
  title?: string;
  className?: string;
}

/** shadcn Checkbox plus shift-click awareness, and it never triggers its row's click. */
export function Checkbox({ checked, onCheckedChange, ...rest }: CheckboxProps) {
  const shift = useRef(false);
  return (
    <UiCheckbox
      checked={checked}
      onPointerDown={(e) => { shift.current = e.shiftKey; }}
      onKeyDown={(e) => { shift.current = e.shiftKey; }}
      onClick={(e) => e.stopPropagation()}
      onCheckedChange={(v) => onCheckedChange(v === true, { shiftKey: shift.current })}
      {...rest}
    />
  );
}

/* ------------------------------------------------------------------ search + unit inputs */

export interface SearchInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'onChange'> {
  value: string;
  onChange: (v: string) => void;
  /** Keyboard hint shown at the right, e.g. "/". */
  hint?: string;
  ref?: Ref<HTMLInputElement>;
}

// React 19: ref is a plain prop, no forwardRef.
export function SearchInput({ value, onChange, hint, className, ref, ...rest }: SearchInputProps) {
  return (
    <div className={cn('relative flex items-center', className)}>
      <Search className="pointer-events-none absolute left-2.5 size-3.5 text-t3" />
      <input ref={ref} type="search" value={value} onChange={(e) => onChange(e.target.value)} autoComplete="off" className={cn(fieldClass, 'pl-8', hint && 'pr-8')} {...rest} />
      {hint && !value && <Kbd className="pointer-events-none absolute right-2">{hint}</Kbd>}
    </div>
  );
}

/** Input with a unit attached, e.g. [ 10 | copies ]. Takes a ref for React Hook Form. */
export function UnitInput({ unit, className, ref, ...rest }: InputHTMLAttributes<HTMLInputElement> & { unit: string; ref?: Ref<HTMLInputElement> }) {
  return (
    <label className={cn('inline-flex items-center overflow-hidden rounded-sm border border-line2 bg-input focus-within:border-[var(--focus)] has-[input[aria-invalid=true]]:border-bad', className)}>
      <input ref={ref} className="h-[30px] w-14 bg-transparent px-2 text-right tabular-nums text-t1 outline-hidden" {...rest} />
      <span className="pr-2.5 pl-1 text-xs text-t3">{unit}</span>
    </label>
  );
}

/* ------------------------------------------------------------------ segmented */

export interface SegmentOption<T extends string> {
  value: T;
  label: ReactNode;
  count?: number;
  icon?: ReactNode;
  /** Colour the count, e.g. issues > 0. */
  hot?: boolean;
}

/** shadcn ToggleGroup as a filled segmented control. Always has exactly one value. */
export function Segmented<T extends string>({ options, value, onChange, 'aria-label': label, className, size = 'md' }: {
  options: SegmentOption<T>[]; value: T; onChange: (v: T) => void; 'aria-label': string; className?: string; size?: 'sm' | 'md';
}) {
  return (
    <ToggleGroup type="single" value={value} onValueChange={(v) => { if (v) onChange(v as T); }} aria-label={label} className={className}>
      {options.map((o) => (
        <ToggleGroupItem key={o.value} value={o.value} aria-pressed={o.value === value} className={size === 'sm' ? 'h-6' : undefined}>
          {o.icon}{o.label}
          {o.count !== undefined && <span className={cn('text-caption tabular-nums', o.hot ? 'text-warn' : o.value === value ? 'text-t2' : 'text-t4')}>{o.count}</span>}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
