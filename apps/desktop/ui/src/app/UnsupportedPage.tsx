import { Page, PageHeader } from '@/components/bayle/layout';
import type { Game } from '@/api';

/** Shown for games Bayle knows about but cannot mod yet. Launch, mods and saves stay off. */
export function UnsupportedPage({ game }: { game: Game }) {
  return (
    <Page>
      <PageHeader eyebrow={game.name} title="Not supported yet"
        subtitle={`Support for ${game.name} is coming. Launch, mods and saves stay off on this game until then, so nothing here can change them.`} />
      {game.installFolder && <div className="text-ui text-t3">Found at <span className="font-mono text-t2">{game.installFolder}</span></div>}
    </Page>
  );
}
