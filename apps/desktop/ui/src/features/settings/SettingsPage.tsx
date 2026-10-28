import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useAppInfo, useCall, useDefaultSettings, useGames, useSettings } from '@/data/hooks';
import { useSearchRequest } from '@/app/nav';
import { toast } from '@/state/toasts';
import { EmptyState, Page, PageHeader } from '@/components/bayle/layout';
import { LinkButton } from '@/components/ui/button';
import { ConfirmDialog } from '@/components/bayle/overlay';
import { SettingsContext, type SettingsCtx } from './context';
import { buildSchema, isChanged, patchFor, resetPatch, rowMatches, SECTIONS, type RowDef, type SectionId } from './schema';
import { SettingsNav } from './SettingsNav';
import { Section } from './sections/Section';
import { useScrollSpy } from './useScrollSpy';

/** Launcher-wide settings. Every control saves as you change it; Reset puts defaults back. */
export function SettingsPage() {
  const settings = useSettings();
  const defaults = useDefaultSettings();
  const games = useGames();
  const info = useAppInfo();
  const call = useCall();
  const [query, setQuery] = useState('');
  const [confirmReset, setConfirmReset] = useState<RowDef[] | null>(null);
  const search = useRef<HTMLInputElement>(null);

  const schema = useMemo(() => buildSchema(games.data ?? []), [games.data]);
  const s = settings.data;
  const d = defaults.data;

  const visible = useMemo(() => SECTIONS.map((sec) => ({ sec, rows: schema.filter((r) => r.section === sec.id && rowMatches(r, query.trim(), sec.title)) })), [schema, query]);
  const changedRows = useMemo(() => (s && d ? schema.filter((r) => isChanged(r, s, d)) : []), [schema, s, d]);
  const { active, jump } = useScrollSpy(SECTIONS.map((x) => x.id), !!(s && d));

  const set = useCallback<SettingsCtx['set']>((path, value) => {
    if (!s) return;
    void call((a) => a.updateSettings(patchFor(s, path, value)));
  }, [s, call]);
  const reset = useCallback((rows: RowDef[]) => {
    if (!s || !d || !rows.length) return;
    void call((a) => a.updateSettings(resetPatch(rows, s, d)), { title: rows.length === 1 ? `${rows[0]!.label}: back to the default` : `${rows.length} settings back to their defaults` });
  }, [s, d, call]);

  // /settings?section=<id> (command palette) scrolls to that section.
  useSearchRequest('/settings', 'section', (id) => requestAnimationFrame(() => jump(id as SectionId)));

  // "/" focuses search on this page.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/' || (e.target as HTMLElement | null)?.closest('input,textarea,select')) return;
      e.preventDefault(); search.current?.focus();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const ctx = useMemo<SettingsCtx | null>(() => (s && d ? { settings: s, defaults: d, info: info.data, games: (games.data ?? []).filter((g) => g.supported), set, reset, askResetAll: () => setConfirmReset(changedRows) } : null), [s, d, info.data, games.data, set, reset, changedRows]);

  const searching = !!query.trim();
  const anyMatch = visible.some((v) => v.rows.length);

  return (
    <Page>
      <PageHeader eyebrow="All games · this computer" title="Settings" subtitle="Changes save as you make them. A gold dot marks anything you changed from the default." />
      {!ctx ? <div className="py-10 text-center text-ui text-t3">Loading settings…</div> : (
        <SettingsContext.Provider value={ctx}>
          <div className="grid grid-cols-[280px_minmax(0,1fr)] items-start gap-7 max-[980px]:grid-cols-1 max-[980px]:gap-4">
            <SettingsNav ref={search} query={query} onQuery={setQuery} active={active} onJump={(id) => { if (searching && !visible.find((v) => v.sec.id === id)?.rows.length) setQuery(''); requestAnimationFrame(() => jump(id)); }}
              items={visible.map(({ sec, rows }) => ({ id: sec.id, title: sec.title, matches: rows.length, changed: schema.filter((r) => r.section === sec.id && isChanged(r, ctx.settings, ctx.defaults)).length }))}
              updateAvailable={!!info.data?.update} totalChanged={changedRows.length} onResetAll={() => setConfirmReset(changedRows)}
              versions={`Bayle ${info.data?.version ?? ''} · me3 ${info.data?.me3Version ?? ''}`} />
            <div className="flex min-w-0 flex-col gap-10">
              {!anyMatch && <EmptyState title="No setting matches." action={<LinkButton onClick={() => setQuery('')}>Clear search</LinkButton>} />}
              {visible.filter((v) => v.rows.length).map(({ sec, rows }) => <Section key={sec.id} section={sec} rows={rows} searching={searching} />)}
            </div>
          </div>
          <ConfirmDialog open={!!confirmReset} onOpenChange={(o) => !o && setConfirmReset(null)} danger confirmLabel="Reset"
            title={confirmReset?.length ? `Reset ${confirmReset.length} setting${confirmReset.length === 1 ? '' : 's'} to the default?` : 'Everything is already at its default'}
            description="Folders you picked are kept. Your mods and saves are not touched."
            onConfirm={() => { if (confirmReset?.length) reset(confirmReset); else toast({ kind: 'info', title: 'Everything is already at its default' }); }}>
            {!!confirmReset?.length && <ul className="m-0 flex flex-col gap-1 pl-[18px] text-ui text-t2">{confirmReset.map((r) => <li key={r.id}>{r.label}</li>)}</ul>}
          </ConfirmDialog>
        </SettingsContext.Provider>
      )}
    </Page>
  );
}

