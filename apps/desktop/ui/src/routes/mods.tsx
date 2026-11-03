import { createFileRoute } from '@tanstack/react-router';
import { z } from 'zod';
import { ModsPage } from '@/features/mods/ModsPage';

/** ?mod=<id> opens that mod's panel (used by search, Activity and links). */
export const Route = createFileRoute('/mods')({
  validateSearch: z.object({ mod: z.string().optional() }),
  component: ModsPage,
});
