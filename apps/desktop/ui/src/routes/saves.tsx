import { createFileRoute } from '@tanstack/react-router';
import { SavesPage } from '@/features/saves/SavesPage';

export const Route = createFileRoute('/saves')({
  component: SavesPage,
});
