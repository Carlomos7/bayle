import { useState } from 'react';
import { hueOf, initials } from '@/lib/thumb';
import { cn } from '@/lib/utils';

/**
 * A mod's thumbnail. Uses the real image when there is one (and falls back if
 * it fails to load); until Bayle can fetch thumbnails, a placeholder: the
 * mod's initials on a colour picked from its name. Decorative: the name is
 * always written next to it, so it is hidden from screen readers.
 */
export function ModThumb({ name, src, size = 32, dim, className }: { name: string; src?: string; size?: number; dim?: boolean; className?: string }) {
  const [failed, setFailed] = useState(false);
  const hue = hueOf(name);
  const box = cn('relative grid shrink-0 place-items-center overflow-hidden rounded-md select-none', dim && 'opacity-50 grayscale', className);
  if (src && !failed) {
    return <img src={src} alt="" aria-hidden width={size} height={size} onError={() => setFailed(true)} className={cn(box, 'object-cover')} style={{ width: size, height: size }} />;
  }
  return (
    <span aria-hidden data-thumb="placeholder" className={box}
      style={{
        width: size, height: size, fontSize: Math.round(size * 0.38),
        background: `linear-gradient(135deg, oklch(0.62 0.13 ${hue}) 0%, oklch(0.42 0.11 ${(hue + 40) % 360}) 100%)`,
        boxShadow: 'inset 0 0 0 1px color-mix(in srgb, white 14%, transparent)',
      }}>
      <span className="font-sans font-semibold tracking-tight not-italic text-white/95 [text-shadow:0_1px_1px_rgb(0_0_0/.35)]">{initials(name)}</span>
    </span>
  );
}
