import * as React from 'react';
import { cn } from '@/lib/utils';

/** Shared look for text-like fields, reused by native-select and textarea. */
export const fieldClass = 'h-8 w-full min-w-0 rounded-sm border border-line2 bg-input px-2.5 text-body text-t1 outline-hidden transition-colors placeholder:text-t4 focus-visible:border-[var(--focus)] focus-visible:shadow-[0_0_0_3px_color-mix(in_srgb,var(--focus)_35%,transparent)] disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-bad aria-invalid:shadow-[0_0_0_3px_var(--bad-bg)]';

function Input({ className, type, ...props }: React.ComponentProps<'input'>) {
  return <input type={type} data-slot="input" className={cn(fieldClass, className)} {...props} />;
}

export { Input };
