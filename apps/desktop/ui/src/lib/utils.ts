import { clsx, type ClassValue } from 'clsx';
import { extendTailwindMerge } from 'tailwind-merge';

/**
 * tailwind-merge has to know the theme's custom scales, or it can't tell what
 * a class does: an unknown `text-ui` would be read as a colour and dropped
 * next to `text-t3`. Keep this list in step with the @theme text scale in
 * src/styles/index.css.
 */
const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      text: ['badge', 'tag', 'micro', 'caption', 'code', 'ui', 'body', 'emphasis', 'section', 'heading', 'title', 'display'],
    },
  },
});

/** shadcn's class helper: join class names, later Tailwind classes win. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
