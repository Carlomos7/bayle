import { type ReactNode } from 'react';
import { SectionLabel } from '@/components/bayle/layout';
import { cn } from '@/lib/utils';

/* ------------------------------------------------------------------ small form pieces */

export function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-line2 bg-[color-mix(in_srgb,var(--t1)_1.5%,var(--panel))] px-4 pt-3 pb-1">
      <SectionLabel className="mb-1">{title}</SectionLabel>
      <div className="divide-y divide-line">{children}</div>
    </section>
  );
}

export function Row({ label, help, htmlFor, children, stacked }: { label: string; help?: ReactNode; htmlFor?: string; children: ReactNode; stacked?: boolean }) {
  return (
    <div className={cn('gap-4 py-3', stacked ? 'flex flex-col gap-2' : 'grid grid-cols-[1fr_auto] items-start')}>
      <div>
        <label htmlFor={htmlFor} className="block text-body font-medium">{label}</label>
        {help && <p className="m-0 mt-0.5 text-xs leading-snug text-t3">{help}</p>}
      </div>
      {children}
    </div>
  );
}

export function FieldError({ message }: { message?: string }) {
  return message ? <p role="alert" className="m-0 text-xs text-bad">{message}</p> : null;
}
