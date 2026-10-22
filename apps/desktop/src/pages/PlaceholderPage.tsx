import type { ReactNode } from "react";

/** Stands in for a page until its work package lands. */
export function PlaceholderPage({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <section aria-labelledby="page-title" className="flex flex-col gap-4">
      <h1 id="page-title" className="font-semibold text-page text-title">
        {title}
      </h1>
      {children ?? <p className="text-text-secondary">This page is not built yet.</p>}
    </section>
  );
}
