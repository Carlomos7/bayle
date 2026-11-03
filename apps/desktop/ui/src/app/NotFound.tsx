import { Link } from '@tanstack/react-router';
import { Page, PageHeader } from '@/components/bayle/layout';

export function NotFound() {
  return (
    <Page>
      <PageHeader title="Nothing here" subtitle={<>That page doesn't exist. <Link to="/mods" className="text-accent hover:underline">Back to Mods</Link></>} />
    </Page>
  );
}
