import type { ReactNode, Ref } from 'react';
import { Bell, Code, FileText, Folder, Info, Moon, Play, Save, SlidersHorizontal } from 'lucide-react';
import { SearchInput } from '@/components/bayle/controls';
import { LinkButton } from '@/components/ui/button';
import { cn, plural } from '@/lib/utils';
import type { SectionId } from './schema';

const ICON: Record<SectionId, ReactNode> = {
  locations: <Folder />, launch: <Play />, backups: <Save />, appearance: <Moon />, updates: <Bell />,
  logs: <FileText />, shortcuts: <Code />, advanced: <SlidersHorizontal />, about: <Info />,
};

export interface NavItem { id: SectionId; title: string; changed: number; matches: number }

interface Props {
  items: NavItem[];
  active: string;
  query: string;
  onQuery: (q: string) => void;
  onJump: (id: SectionId) => void;
  updateAvailable: boolean;
  totalChanged: number;
  onResetAll: () => void;
  versions: string;
}

/** Sticky: search, sections (with changed counts), and the changed-from-default summary. */
export function SettingsNav({ items, active, query, onQuery, onJump, updateAvailable, totalChanged, onResetAll, versions, ref }: Props & { ref?: Ref<HTMLInputElement> }) {
  return (
    <nav aria-label="Settings sections" className="sticky top-5 flex flex-col gap-0.5 max-[980px]:static max-[980px]:flex-row max-[980px]:flex-wrap">
      <SearchInput ref={ref} value={query} onChange={onQuery} hint="/" placeholder="Search settings" aria-label="Search settings" className="mb-2.5 w-full max-[980px]:mb-0 max-[980px]:w-[220px]" />
      {items.map((s) => {
        const on = s.id === active && !(query && !s.matches);
        return (
          <button key={s.id} type="button" onClick={() => onJump(s.id)} aria-current={on ? 'true' : undefined}
            className={cn('relative flex h-9 items-center gap-2.5 rounded-lg px-3 text-left text-body text-t2 transition-colors hover:bg-t1/5 hover:text-t1 [&>svg]:size-[15px] [&>svg]:text-t3',
              on && 'bg-t1/9 font-[550] text-t1 [&>svg]:text-accent before:absolute before:top-[9px] before:bottom-[9px] before:left-0 before:w-[3px] before:rounded-xs before:bg-accent',
              query && !s.matches && 'opacity-40')}>
            {ICON[s.id]}
            <span className="flex-1 truncate">{s.title}</span>
            {s.changed > 0 && <span title={`${plural(s.changed, 'setting')} changed from the default`} className="grid h-[18px] min-w-[18px] place-items-center rounded-full bg-accent-soft px-[5px] text-micro font-semibold text-accent">{s.changed}</span>}
            {s.id === 'updates' && updateAvailable && <span aria-label="An update is available" className="size-[7px] rounded-full bg-accent" />}
          </button>
        );
      })}
      <div className="mt-3.5 flex flex-col gap-1.5 border-t border-line px-3 pt-3 text-caption text-t4 max-[980px]:hidden">
        {totalChanged > 0 && (
          <span className="flex items-center gap-[7px] text-t2">
            <span className="size-1.5 rounded-full bg-accent" />{totalChanged} changed from default
            <LinkButton className="ml-auto text-caption" onClick={onResetAll}>Reset all</LinkButton>
          </span>
        )}
        <span>{versions}</span>
      </div>
    </nav>
  );
}
