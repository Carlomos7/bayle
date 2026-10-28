import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

/** Same header on every page: scope line, serif title, one-line subtitle, actions on the right. */
export function PageHeader({ eyebrow, title, subtitle, actions, children }: { eyebrow?: ReactNode; title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-start gap-4">
      <div className="min-w-0 flex-1 basis-[420px]">
        {eyebrow && <div className="mb-2 flex items-center gap-2 text-xs font-medium tracking-[.1em] text-t3 uppercase">{eyebrow}</div>}
        <h1 className="m-0 font-serif text-display leading-[1.1] font-semibold text-t1 [text-wrap:balance]">{title}</h1>
        {subtitle && <div className="mt-2 flex flex-wrap items-center gap-2 text-ui text-t3">{subtitle}</div>}
        {children}
      </div>
      {actions && <div className="flex min-h-8 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

/** Page container: same width, padding and spacing everywhere. */
export function Page({ children, className, id }: { children: ReactNode; className?: string; id?: string }) {
  return <section id={id} className={cn('mx-auto flex w-full max-w-[1200px] flex-col gap-5 px-8 pt-6 pb-12 max-[820px]:px-4', className)}>{children}</section>;
}

/** The toolbar under a page header: search first, filters, then the rest on the right. */
export function Toolbar({ children, className, sticky }: { children: ReactNode; className?: string; sticky?: boolean }) {
  return <div role="toolbar" className={cn('flex flex-wrap items-center gap-2.5', sticky && 'sticky top-0 z-10 -my-2.5 bg-bg py-2.5', className)}>{children}</div>;
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('rounded-lg border border-line2 bg-panel', className)}>{children}</div>;
}

/** Small uppercase label inside cards and panels. */
export function SectionLabel({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('text-micro font-semibold tracking-[.08em] text-t3 uppercase', className)}>{children}</div>;
}

export function EmptyState({ title, children, action }: { title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line2 px-6 py-10 text-center">
      <div className="font-semibold">{title}</div>
      {children && <div className="mx-auto mt-1 max-w-md text-ui text-t3">{children}</div>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

/** Coloured strip for things that need a look, one line each. */
export function Notice({ tone = 'info', icon, title, children, actions }: { tone?: 'info' | 'warn' | 'bad' | 'ok'; icon?: ReactNode; title: ReactNode; children?: ReactNode; actions?: ReactNode }) {
  const bar = { info: 'shadow-[inset_3px_0_0_var(--info)]', warn: 'shadow-[inset_3px_0_0_var(--warn)]', bad: 'shadow-[inset_3px_0_0_var(--bad)]', ok: 'shadow-[inset_3px_0_0_var(--ok)]' }[tone];
  const ic = { info: 'text-info', warn: 'text-warn', bad: 'text-bad', ok: 'text-ok' }[tone];
  return (
    <div className={cn('grid min-h-12 grid-cols-[20px_1fr_auto] items-center gap-x-3 gap-y-2 border-b border-line bg-panel py-2 pr-3 pl-3.5 last:border-b-0 max-[700px]:grid-cols-[20px_1fr]', bar)}>
      <span className={cn('self-start pt-0.5 [&_svg]:size-4', ic)}>{icon}</span>
      <div className="min-w-0 text-body leading-snug"><b className="font-semibold">{title}</b>{children && <span className="ml-1.5 text-ui text-t2">{children}</span>}</div>
      {actions && <div className="flex flex-wrap items-center justify-end gap-1.5 max-[700px]:col-start-2 max-[700px]:justify-start">{actions}</div>}
    </div>
  );
}

/** Wordmark image ("BAYLE · FromSoft Mod Manager"), themed. */
export function Wordmark({ width = 240, className }: { width?: number; className?: string }) {
  return <div role="img" aria-label="Bayle, FromSoft Mod Manager" className={cn('shrink-0 bg-[image:var(--wordmark)] bg-contain bg-left bg-no-repeat', className)} style={{ width, aspectRatio: '640 / 307' }} />;
}

export function LogoMark({ size = 20, className }: { size?: number; className?: string }) {
  return <span aria-hidden className={cn('inline-block shrink-0 bg-[image:var(--logo)] bg-contain bg-center bg-no-repeat', className)} style={{ width: size, height: size }} />;
}
