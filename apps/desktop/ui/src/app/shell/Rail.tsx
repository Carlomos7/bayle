import { GitMerge, History, Layers, Save, Settings, SlidersHorizontal } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from '@tanstack/react-router';
import { useUi } from '@/state/ui';
import { usePage, type PageId } from '@/app/nav';
import { useCurrent } from '@/data/hooks';
import { CountBadge, Kbd } from '@/components/bayle/badge';
import { Tooltip } from '@/components/bayle/overlay';
import { cn } from '@/lib/utils';

const ITEMS: { id: PageId; label: string; hint: string; kbd: string; icon: ReactNode; gameOnly?: boolean }[] = [
  { id: 'mods', label: 'Mods', hint: 'load order, packages, natives', kbd: 'Ctrl 1', icon: <Layers />, gameOnly: true },
  { id: 'saves', label: 'Saves', hint: 'check, repair, copies', kbd: 'Ctrl 2', icon: <Save />, gameOnly: true },
  { id: 'merge', label: 'Merge', hint: 'what was merged, who won, what to fix', kbd: 'Ctrl 3', icon: <GitMerge />, gameOnly: true },
  { id: 'configs', label: 'Mod Configs', hint: 'settings files', kbd: 'Ctrl 4', icon: <SlidersHorizontal />, gameOnly: true },
  { id: 'activity', label: 'Activity', hint: 'every launch, install and rebuild', kbd: 'Ctrl 5', icon: <History /> },
];

function RailButton({ id, label, hint, kbd, icon, badge }: { id: PageId; label: string; hint: string; kbd: string; icon: ReactNode; badge?: number }) {
  const on = usePage() === id;
  return (
    <Tooltip content={<><b className="font-medium">{label}</b><span className="text-t3">{hint}</span><Kbd>{kbd}</Kbd></>}>
      <Link to={`/${id}`} aria-label={label} aria-current={on ? 'page' : undefined}
        className={cn('relative grid size-10 place-items-center rounded-sm text-t3 transition-colors hover:bg-hover hover:text-t1 [&_svg]:size-[18px]',
          on && 'bg-accent-soft text-accent before:absolute before:top-2.5 before:bottom-2.5 before:-left-2 before:w-[3px] before:rounded-r-xs before:bg-accent hover:bg-accent-soft hover:text-accent')}>
        {icon}
        {!!badge && <CountBadge n={badge} className="absolute top-1 right-0.5" />}
      </Link>
    </Tooltip>
  );
}

/** Fixed icon rail on the left; Settings sits at the bottom. */
export function Rail() {
  const { game } = useCurrent();
  const fails = useUi((s) => s.unseenFailures);
  return (
    <nav aria-label="Pages" className="relative z-10 flex flex-col items-center gap-1 bg-side py-2 shadow-[inset_-1px_0_0_var(--line)]">
      {ITEMS.filter((i) => !i.gameOnly || game?.supported).map((i) => <RailButton key={i.id} {...i} badge={i.id === 'activity' ? fails : undefined} />)}
      <span className="flex-1" />
      <span className="mb-1 h-px w-8 bg-line" />
      <RailButton id="settings" label="Settings" hint="launcher-wide" kbd="Ctrl 6" icon={<Settings />} />
    </nav>
  );
}
