import * as React from 'react';
import { ChevronDown } from 'lucide-react';
import { cn } from '@/lib/utils';
import { fieldClass } from './input';

/** A styled native <select>: cheap enough for hundreds of rows (file trees). */
function NativeSelect({ className, children, ...props }: React.ComponentProps<'select'>) {
  return (
    <div data-slot="native-select-wrapper" className="relative inline-flex w-auto">
      <select data-slot="native-select" className={cn(fieldClass, 'w-auto appearance-none pr-7', className)} {...props}>{children}</select>
      <ChevronDown className="pointer-events-none absolute top-1/2 right-2 size-3.5 -translate-y-1/2 text-t3" />
    </div>
  );
}

export { NativeSelect };
