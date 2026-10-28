import { createFileRoute, redirect } from '@tanstack/react-router';

/** Bayle opens on Mods. */
export const Route = createFileRoute('/')({
  beforeLoad: () => { throw redirect({ to: '/mods' }); },
});
