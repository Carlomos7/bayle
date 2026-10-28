import * as React from 'react';
import { ToggleGroup as ToggleGroupPrimitive } from 'radix-ui';
import { cn } from '@/lib/utils';

/** Filled segmented control: one choice from a few (filters, settings values). Arrow keys move between items. */
function ToggleGroup({ className, ...props }: React.ComponentProps<typeof ToggleGroupPrimitive.Root>) {
  return <ToggleGroupPrimitive.Root data-slot="toggle-group" className={cn('inline-flex w-max max-w-full shrink-0 flex-wrap items-center gap-0.5 rounded-lg border border-line bg-t1/4 p-[3px]', className)} {...props} />;
}
function ToggleGroupItem({ className, ...props }: React.ComponentProps<typeof ToggleGroupPrimitive.Item>) {
  return (
    <ToggleGroupPrimitive.Item data-slot="toggle-group-item"
      className={cn("inline-flex h-[26px] items-center gap-1.5 rounded-xs px-2.5 text-ui whitespace-nowrap text-t3 transition-colors outline-hidden hover:bg-t1/6 hover:text-t1 focus-visible:shadow-[0_0_0_2px_var(--focus)] data-[state=on]:bg-t1/12 data-[state=on]:font-semibold data-[state=on]:text-t1 data-[state=on]:shadow-[inset_0_0_0_1px_var(--line2)] [&_svg:not([class*='size-'])]:size-3.5 [&_svg]:opacity-80", className)}
      {...props} />
  );
}

export { ToggleGroup, ToggleGroupItem };
