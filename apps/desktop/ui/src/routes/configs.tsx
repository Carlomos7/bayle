import { createFileRoute } from '@tanstack/react-router';
import { z } from 'zod';
import { ConfigsPage } from '@/features/configs/ConfigsPage';

/** ?file=<config file id> selects that file; ids starting with "setup:" open the overhaul setup. */
export const Route = createFileRoute('/configs')({
  validateSearch: z.object({ file: z.string().optional() }),
  component: ConfigsPage,
});
