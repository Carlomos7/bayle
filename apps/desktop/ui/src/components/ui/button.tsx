import * as React from 'react';
import { Slot } from 'radix-ui';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

/**
 * shadcn/ui Button, themed for Bayle.
 * Extra variants: primary (the one main action), danger, ghost-danger.
 * Extra props: `icon` (leading icon) and `iconOnly` (square; needs aria-label).
 */
const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-sm border text-body font-medium transition-colors outline-hidden disabled:pointer-events-none disabled:opacity-60 focus-visible:ring-[3px] focus-visible:ring-ring/50 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: 'border-line2 bg-transparent text-t1 hover:border-t4 hover:bg-hover',
        outline: 'border-line2 bg-transparent text-t1 hover:border-t4 hover:bg-hover',
        primary: 'border-transparent bg-accent-fill font-semibold text-on-accent hover:bg-accent-fill-2 disabled:border-line2 disabled:bg-raise disabled:text-t3 disabled:opacity-100',
        secondary: 'border-transparent bg-raise text-t1 hover:bg-press',
        ghost: 'border-transparent bg-transparent text-t2 hover:bg-hover hover:text-t1',
        destructive: 'border-transparent bg-bad text-bg hover:brightness-110',
        danger: 'border-bad/45 bg-transparent text-bad hover:bg-bad-bg',
        'ghost-danger': 'border-transparent bg-transparent text-bad hover:bg-bad-bg',
        link: 'border-transparent bg-transparent px-0 text-accent underline-offset-2 hover:underline',
      },
      size: {
        default: 'h-8 px-3',
        md: 'h-8 px-3',
        sm: "h-7 gap-1.5 px-2.5 text-ui [&_svg:not([class*='size-'])]:size-3.5",
        lg: 'h-9 px-4',
        icon: 'size-8 px-0',
        'icon-sm': "size-7 px-0 [&_svg:not([class*='size-'])]:size-3.5",
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
);

export interface ButtonProps extends React.ComponentProps<'button'>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  icon?: React.ReactNode;
  iconOnly?: boolean;
}

function Button({ className, variant, size, asChild = false, icon, iconOnly, children, type = 'button', ...props }: ButtonProps) {
  const Comp = asChild ? Slot.Root : 'button';
  const s = iconOnly ? (size === 'sm' ? 'icon-sm' : 'icon') : size;
  return (
    <Comp data-slot="button" type={asChild ? undefined : type} className={cn(buttonVariants({ variant, size: s, className }))} {...props}>
      {asChild ? children : <>{icon}{children}</>}
    </Comp>
  );
}

/** Text-only action that reads as a link. */
function LinkButton({ className, ...props }: React.ComponentProps<'button'>) {
  return <button type="button" className={cn('cursor-pointer text-accent underline-offset-2 hover:underline disabled:text-t4 disabled:no-underline', className)} {...props} />;
}

// eslint-disable-next-line react-refresh/only-export-components -- shadcn convention
export { Button, LinkButton, buttonVariants };
