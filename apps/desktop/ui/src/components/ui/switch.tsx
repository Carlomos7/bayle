import * as React from 'react';
import { Switch as SwitchPrimitive } from 'radix-ui';
import { cn } from '@/lib/utils';

/** On/off that applies straight away. Uses the theme's "on" colour, never its alarm red. */
function Switch({ className, size = 'md', ...props }: React.ComponentProps<typeof SwitchPrimitive.Root> & { size?: 'sm' | 'md' }) {
  return (
    <SwitchPrimitive.Root data-slot="switch" data-size={size}
      className={cn('peer inline-flex shrink-0 items-center rounded-full bg-t1/14 transition-colors outline-hidden focus-visible:shadow-[0_0_0_3px_var(--focus)] disabled:cursor-not-allowed disabled:opacity-40 data-[state=checked]:bg-on',
        size === 'sm' ? 'h-[15px] w-[26px]' : 'h-[18px] w-8', className)}
      {...props}>
      <SwitchPrimitive.Thumb data-slot="switch-thumb"
        className={cn('pointer-events-none block rounded-full bg-[color-mix(in_srgb,var(--t1)_70%,var(--panel))] shadow-[0_1px_2px_rgb(0_0_0/.45)] transition-transform data-[state=checked]:bg-on-ink',
          size === 'sm' ? 'size-[11px] translate-x-[2px] data-[state=checked]:translate-x-[13px]' : 'size-[14px] translate-x-[2px] data-[state=checked]:translate-x-[16px]')} />
    </SwitchPrimitive.Root>
  );
}

export { Switch };
