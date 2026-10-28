import type { ThemeName } from '@/api';
import { cn } from '@/lib/utils';
import icon from '@/assets/icon64l.png';

interface Preview { value: ThemeName; label: string; bg: string; panel: string; accent: string; text: string; split?: boolean; sigil?: boolean }

const THEMES: Preview[] = [
  { value: 'dark', label: 'Dark', bg: '#0E0E0D', panel: '#1A1A18', accent: '#F3C04A', text: '#ECE3CF' },
  { value: 'bayle', label: 'Bayle', bg: '#09090B', panel: '#18181C', accent: '#E5383B', text: '#EDEDF0', sigil: true },
  { value: 'tarnished', label: 'Tarnished', bg: '#0C0E07', panel: '#191D0E', accent: '#F3C04A', text: '#E3E6CF' },
  { value: 'light', label: 'Light', bg: '#F4F6FA', panel: '#FFFFFF', accent: '#2457C5', text: '#1B2A44' },
  { value: 'system', label: 'Match Windows', bg: '#0E0E0D', panel: '#1A1A18', accent: '#F3C04A', text: '#ECE3CF', split: true },
];

/** Five preview cards, so you see what you get before picking. */
export function ThemePicker({ value, onChange }: { value: ThemeName; onChange: (t: ThemeName) => void }) {
  return (
    <div role="radiogroup" aria-label="Theme" className="grid w-full grid-cols-5 gap-2.5 max-[980px]:grid-cols-2">
      {THEMES.map((t) => {
        const on = t.value === value;
        return (
          <button key={t.value} type="button" role="radio" aria-checked={on} onClick={() => onChange(t.value)}
            className={cn('flex flex-col gap-[7px] rounded-lg border p-1.5 pb-2 text-left text-ui transition-colors',
              on ? 'border-accent font-[550] text-t1 shadow-[0_0_0_1px_var(--accent)]' : 'border-line2 text-t2 hover:border-t1/28')}>
            <span className="relative block h-[58px] overflow-hidden rounded-sm border border-[rgb(128_128_128/.18)]" style={{ background: t.bg }}>
              <span className="absolute inset-y-0 left-0 w-4" style={{ background: t.panel }} />
              <span className="absolute top-3 right-2.5 left-6 h-[7px] rounded-xs opacity-55" style={{ background: t.text }} />
              <span className="absolute top-7 left-6 h-3.5 w-[34px] rounded-sm" style={{ background: t.accent }} />
              {t.sigil && <img src={icon} alt="" className="absolute right-1.5 bottom-1.5 size-[26px] opacity-90" />}
              {t.split && <span className="absolute inset-0" style={{ background: 'linear-gradient(135deg, transparent 50%, #F4F6FA 50%)' }} />}
            </span>
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
