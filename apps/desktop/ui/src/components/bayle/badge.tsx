import type { ReactNode } from 'react';
import type { Tone } from '@/api';
import { cn } from '@/lib/utils';

const toneTag: Record<Tone, string> = {
  neutral: 'bg-t1/6 border-t1/10 text-t2',
  accent: 'bg-accent-soft border-accent-ring text-accent',
  info: 'bg-info-bg border-info/28 text-info',
  vio: 'bg-vio-bg border-vio/28 text-vio',
  ok: 'bg-ok-bg border-ok/28 text-ok',
  warn: 'bg-warn-bg border-warn/30 text-warn',
  bad: 'bg-bad-bg border-bad/30 text-bad',
};

/**
 * Small label next to a name. Colour carries meaning:
 * info = shared, vio = part of an overhaul, warn = needs care, neutral = how it loads.
 */
export function Tag({ tone = 'neutral', className, children }: { tone?: Tone; className?: string; children: ReactNode }) {
  return (
    <span className={cn('inline-flex h-[19px] shrink-0 items-center gap-1 whitespace-nowrap rounded-xs border px-1.5 text-micro font-medium leading-none', toneTag[tone], className)}>
      {children}
    </span>
  );
}

export type StatusTone = 'ok' | 'warn' | 'bad' | 'off' | 'info' | 'accent';

const toneChip: Record<StatusTone, string> = {
  ok: 'bg-ok-bg text-ok', warn: 'bg-warn-bg text-warn', bad: 'bg-bad-bg text-bad', info: 'bg-info-bg text-info', accent: 'bg-accent-soft text-accent',
  off: 'bg-t1/5 text-t3',
};

/** A state, never a verb: Ready, Overridden, Missing, Off. The dot is a second cue besides colour. */
export function StatusChip({ tone, children, onClick, title }: { tone: StatusTone; children: ReactNode; onClick?: () => void; title?: string }) {
  const cls = cn('inline-flex h-[22px] items-center gap-1.5 whitespace-nowrap rounded-xs pr-2.5 pl-2 text-xs font-medium', toneChip[tone], onClick && 'cursor-pointer hover:brightness-110');
  const dot = <span className={cn('size-1.5 shrink-0 rounded-full', tone === 'off' ? 'shadow-[inset_0_0_0_1.5px_currentColor]' : 'bg-current')} />;
  return onClick
    ? <button type="button" className={cls} onClick={onClick} title={title}>{dot}{children}</button>
    : <span className={cls} title={title}>{dot}{children}</span>;
}

/** Count bubble, e.g. failures on the Activity icon. */
export function CountBadge({ n, className }: { n: number; className?: string }) {
  if (!n) return null;
  return <span className={cn('grid h-4 min-w-4 place-items-center rounded-full bg-bad px-1 text-badge font-bold text-bg', className)}>{n}</span>;
}

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return <kbd className={cn('inline-grid h-5 min-w-5 place-items-center rounded-xs border border-b-2 border-line2 bg-t1/4 px-1.5 font-mono text-micro text-t2', className)}>{children}</kbd>;
}
