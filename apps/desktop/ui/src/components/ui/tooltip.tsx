import * as React from 'react';
import { Tooltip as TooltipPrimitive } from 'radix-ui';
import { cn } from '@/lib/utils';

function TooltipProvider({ delayDuration = 250, ...props }: React.ComponentProps<typeof TooltipPrimitive.Provider>) { return <TooltipPrimitive.Provider data-slot="tooltip-provider" delayDuration={delayDuration} {...props} />; }
function Tooltip(props: React.ComponentProps<typeof TooltipPrimitive.Root>) { return <TooltipPrimitive.Root data-slot="tooltip" {...props} />; }
function TooltipTrigger(props: React.ComponentProps<typeof TooltipPrimitive.Trigger>) { return <TooltipPrimitive.Trigger data-slot="tooltip-trigger" {...props} />; }
function TooltipContent({ className, sideOffset = 8, ...props }: React.ComponentProps<typeof TooltipPrimitive.Content>) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content data-slot="tooltip-content" sideOffset={sideOffset}
        className={cn('z-50 flex items-center gap-2 rounded-sm border border-line2 bg-raise px-2.5 py-1.5 text-xs text-t1 shadow-pop data-[state=delayed-open]:animate-in data-[state=delayed-open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0', className)}
        {...props} />
    </TooltipPrimitive.Portal>
  );
}

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider };
