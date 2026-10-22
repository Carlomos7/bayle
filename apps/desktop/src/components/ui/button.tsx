import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes, Ref } from "react";
import { cn } from "@/lib/cn";

export const buttonVariants = cva(
  "inline-flex h-[var(--control-h)] min-w-22 items-center justify-center gap-2 rounded-control px-4 text-body font-medium transition-colors duration-fast disabled:pointer-events-none disabled:text-text-disabled",
  {
    variants: {
      variant: {
        primary: "border border-gold-line bg-gold-fill-top text-gold-text hover:border-gold-line-hover hover:bg-gold-fill-top-hover",
        danger: "border border-status-danger bg-status-danger-bg text-status-danger hover:bg-status-danger/25",
        ghost: "bg-fill-ghost text-text-primary hover:bg-fill-ghost-hover active:bg-fill-ghost-press",
      },
    },
    defaultVariants: { variant: "ghost" },
  },
);

export function Button({
  className,
  variant,
  ref,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants> & { ref?: Ref<HTMLButtonElement> }) {
  return <button ref={ref} type="button" className={cn(buttonVariants({ variant }), className)} {...props} />;
}
