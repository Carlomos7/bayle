import { createFileRoute } from '@tanstack/react-router';
import { ActivityPage } from '@/features/activity/ActivityPage';
import { useUi } from '@/state/ui';

export const Route = createFileRoute('/activity')({
  // Opening Activity counts as having seen the failures.
  onEnter: () => useUi.getState().clearFailures(),
  component: ActivityPage,
});
