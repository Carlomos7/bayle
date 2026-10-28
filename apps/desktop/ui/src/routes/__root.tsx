import { createRootRoute } from '@tanstack/react-router';
import { AppLayout } from '@/app/AppLayout';
import { NotFound } from '@/app/NotFound';

export const Route = createRootRoute({
  component: AppLayout,
  notFoundComponent: NotFound,
});
