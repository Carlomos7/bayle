import * as React from 'react';
import { Checkbox as CheckboxPrimitive } from 'radix-ui';
import { Check, Minus } from 'lucide-react';
import { cn } from '@/lib/utils';

/** Drawn by the app so it follows every theme; shows a dash when indeterminate. */
function Checkbox({ className, ...props }: React.ComponentProps<typeof CheckboxPrimitive.Root>) {
  return (
    <CheckboxPrimitive.Root data-slot="checkbox"
      className={cn('peer grid size-4 shrink-0 place-items-center rounded-sm border-[1.5px] border-t1/38 bg-input transition-colors outline-hidden hover:border-t1/62 focus-visible:shadow-[0_0_0_3px_var(--focus)] disabled:cursor-not-allowed disabled:opacity-40 data-[state=checked]:border-on data-[state=checked]:bg-on data-[state=indeterminate]:border-on data-[state=indeterminate]:bg-on', className)}
      {...props}>
      <CheckboxPrimitive.Indicator data-slot="checkbox-indicator" className="text-on-ink">
        {props.checked === 'indeterminate' ? <Minus className="size-3" strokeWidth={3} /> : <Check className="size-3" strokeWidth={3.5} />}
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
}

export { Checkbox };
