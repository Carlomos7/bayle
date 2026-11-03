import { createFileRoute } from '@tanstack/react-router';
import { z } from 'zod';
import { SettingsPage } from '@/features/settings/SettingsPage';

/** ?section=<id> scrolls to that section (e.g. appearance, launch). */
export const Route = createFileRoute('/settings')({
  validateSearch: z.object({ section: z.string().optional() }),
  component: SettingsPage,
});
