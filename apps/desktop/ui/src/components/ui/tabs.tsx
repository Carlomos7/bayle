import * as React from 'react';
import { Tabs as TabsPrimitive } from 'radix-ui';
import { cn } from '@/lib/utils';

function Tabs({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Root>) { return <TabsPrimitive.Root data-slot="tabs" className={cn('flex flex-col gap-4', className)} {...props} />; }

/** Filled, full-width segmented tabs (Bayle's style). */
function TabsList({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.List>) {
  return <TabsPrimitive.List data-slot="tabs-list" className={cn('flex gap-0.5 rounded-lg border border-line bg-t1/4 p-[3px]', className)} {...props} />;
}
function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return <TabsPrimitive.Trigger data-slot="tabs-trigger" className={cn('inline-flex h-[30px] flex-1 items-center justify-center gap-1.5 rounded-xs text-ui text-t3 transition-colors outline-hidden hover:bg-t1/6 hover:text-t1 focus-visible:shadow-[0_0_0_2px_var(--focus)] data-[state=active]:bg-t1/12 data-[state=active]:font-semibold data-[state=active]:text-t1 data-[state=active]:shadow-[inset_0_0_0_1px_var(--line2)]', className)} {...props} />;
}
function TabsContent({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Content>) { return <TabsPrimitive.Content data-slot="tabs-content" className={cn('min-h-0 outline-hidden', className)} {...props} />; }

export { Tabs, TabsList, TabsTrigger, TabsContent };
