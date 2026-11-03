import { createFileRoute } from '@tanstack/react-router';
import { z } from 'zod';
import { MergePage } from '@/features/merge/MergePage';

/** ?mod= and ?family= filter the clashes to one cell of the board. */
export const Route = createFileRoute('/merge')({
  validateSearch: z.object({ mod: z.string().optional(), family: z.enum(['params', 'text', 'animations', 'behaviour', 'scripts', 'textures', 'other']).optional() }),
  component: MergePage,
});
