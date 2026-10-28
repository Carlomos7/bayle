import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { connectEngine, resetEngineState } from '@/data/engine';
import { createGateway } from '../hub';
import { createGatewayApi } from '../gatewayApi';
import { fakeTransport, flush } from '../fakeTransport.test-util';
import { forget } from './modsCommon';
import { builtOn, changeOf, toBuildPlan, toBuildReport, type EngineBuild, type EnginePreview } from './builds';

beforeEach(() => { resetEngineState(); forget(PROFILE); });
afterEach(() => resetEngineState());

type Handler = (params: Record<string, unknown> | undefined) => unknown;
async function engine(ops: Record<string, Handler>) {
  const t = fakeTransport({ state: 'ready', epoch: 1 });
  const g = createGateway(t);
  connectEngine(g, new QueryClient());
  await flush(); await flush();
  const base = t.call.bind(t);
  t.call = (async (op: string, params?: Record<string, unknown>, o?: { epoch?: number }) => {
    const h = ops[op];
    if (!h) return base(op, params, o);
    t.calls.push({ operation: op, params, epoch: o?.epoch });
    return h(params);
  }) as typeof t.call;
  return { api: createGatewayApi(g), asked: () => t.calls.map((c) => [c.operation, c.params]) };
}

const PROFILE = 'C:\\P\\Main\\Main.me3';
const DIR = 'C:\\P\\Main';
const entry = (index: number, name: string) => ({ kind: 'package', path: `mod\\${name}`, id: name, enabled: true, load_after: [], load_before: [], index, name });
const page = { profile: PROFILE, has_profile: true, facts: { profile: PROFILE, entries: [entry(0, 'a'), entry(1, 'b'), entry(2, 'c')], display: { package: [0, 1, 2] }, problems: {}, loads_nothing: [], stays_last: [], missing: [], configs: {} } };
const A = `${DIR}\\mod\\a`, B = `${DIR}\\mod\\b`, C = `${DIR}\\mod\\c`;

const built: EngineBuild = {
  state: 'current', reasons: [], built_on: '2026-10-28 00:31:07',
  mods: [{ index: 0, name: 'a' }, { index: 1, name: 'b' }, { index: 2, name: 'c' }],
  files: [
    { path: 'menu/x.sblytbnd.dcx', family: 'other', mods: [0, 1, 2], merged: true, skipped: '', parts: 5, clashes: [{ part: 'p1', mods: [0, 1] }, { part: 'p2', mods: [0, 1] }, { part: 'p3', mods: [1, 2] }], warnings: [] },
    { path: 'chr/c.anibnd.dcx', family: 'animations', mods: [1, 2], merged: false, skipped: 'not an archive', parts: 0, clashes: [], warnings: [] },
  ],
  dropped: [{ id: 'd1', mod: 1, file: 'chr/c.anibnd.dcx', family: 'animations', kind: 'whole_copy', detail: 'not an archive', count: 0, accepted: false }],
};
const ids = new Map([[0, A], [1, B], [2, C]]);
const report = (e: EngineBuild) => toBuildReport(PROFILE, e, (i) => ids.get(i));

describe('builds adapter: the report', () => {
  it('says the engine merges in load order and keeps rules, picks and survival empty', () => {
    const r = report(built);
    expect(r).toMatchObject({ state: 'ready', choices: false, rules: [], pending: [], kept: [], changes: [], families: ['other', 'animations'] });
    expect(r.survival).toBeUndefined();
  });

  it('groups the parts that the same mods met at, the last of them winning, and counts each mod', () => {
    const r = report(built);
    const merged = r.clashes.filter((c) => !c.unsupported);
    expect(merged.map((c) => [c.sides.map((s) => s.modId), c.winnerId, c.reason])).toEqual([[[A, B], B, 'order'], [[B, C], C, 'order']]);
    const cell = (modId: string, family: string, outcome: string) => r.cells.find((c) => c.modId === modId && c.family === family && c.outcome === outcome)?.count;
    expect([cell(A, 'other', 'lost'), cell(B, 'other', 'won'), cell(B, 'other', 'lost'), cell(C, 'other', 'won'), cell(A, 'other', 'merged')]).toEqual([2, 2, 1, 1, 1]);
  });

  it('names a file that is not merged as a whole-file clash won by the last mod, and lists what was left out', () => {
    const r = report(built);
    expect(r.clashes.find((c) => c.unsupported)).toMatchObject({ file: 'chr/c.anibnd.dcx', winnerId: C, sides: [{ modId: B }, { modId: C }] });
    expect(r.cells.filter((c) => c.family === 'animations').map((c) => [c.modId, c.outcome])).toEqual([[B, 'unsupported'], [C, 'unsupported']]);
    expect(r.dropped).toEqual([expect.objectContaining({ id: 'd1', modId: B, family: 'animations', accepted: false })]);
  });

  it('names the mods the build merges, which leaves out its own package', () => {
    expect(report({ ...built, mods: [{ index: 0, name: 'a' }, { index: 2, name: 'c' }] }).mods).toEqual([A, C]);
  });

  it('words inner files a copy lacks as missing from it', () => {
    const r = report({ ...built, dropped: [{ id: 'd2', mod: 2, file: 'menu/x.sblytbnd.dcx', family: 'other', kind: 'lacks', detail: 'c lacks 2 inner files', count: 0, accepted: false }] });
    expect(r.dropped[0]).toMatchObject({ what: 'missing inner files of menu/x.sblytbnd.dcx', reason: 'c lacks 2 inner files' });
  });

  it('is stale with the engine reasons, and none when nothing applies', () => {
    const stale = report({ ...built, state: 'stale', reasons: ['the game was updated since the last build'] });
    expect(stale.state).toBe('stale');
    expect(stale.changes).toEqual([{ kind: 'game-updated', title: 'The game was updated since the last build' }]);
    expect(report({ ...built, state: 'single', files: [], dropped: [] }).state).toBe('none');
    expect(report({ ...built, state: null, files: [], dropped: [] }).state).toBe('none');
    expect(report({ ...built, state: 'single', reasons: ['2 game file(s) two packages ship can be merged so both apply: x'], files: [], dropped: [] }).state).toBe('stale');
  });

  it('reads reasons into change kinds where they say it, else a generic one', () => {
    expect(changeOf('b loads after the combined parameters and replaces them').kind).toBe('reordered');
    expect(changeOf('marker copy changed since the last rebuild').kind).toBe('mod-updated');
    expect(changeOf('the launcher merging changed since this was built').kind).toBe('setup-changed');
    expect(changeOf('made by an earlier version of the launcher').kind).toBe('setup-changed');
  });

  it('words the time of the build', () => {
    expect(builtOn('', new Date())).toBeUndefined();
    expect(builtOn('2026-10-28 00:31:07', new Date(2026, 9, 28, 12))).toMatch(/^today, /);
    expect(builtOn('2026-10-27 09:00:00', new Date(2026, 9, 28, 12))).toMatch(/^yesterday, /);
  });
});

describe('builds adapter: the plan', () => {
  const base: EnginePreview = { state: 'stale', blocked: '', detail: '', tool: '', needs_allow: false, problem: '', files: ['a.dcx', 'b.dcx'], packs: ['x', 'y'], reasons: [] };
  it('composes steps from what the engine says and gives no estimate', () => {
    const p = toBuildPlan(base);
    expect(p.estimateSec).toBeUndefined();
    expect(p.steps.map((s) => s.title)).toEqual(['Combine the parameters of 2 packs', 'Merge 2 game files that more than one mod ships', 'Check the result, then put it in place']);
  });
  it('says first that nothing changed when the build is current', () => {
    expect(toBuildPlan({ ...base, state: 'current' }).steps[0]!.title).toBe('Nothing changed since the last build');
  });
  it('says what blocks it and that a tool needs allowing', () => {
    expect(toBuildPlan({ ...base, blocked: 'rebuild_game_running', files: [], packs: [] }).steps.map((s) => s.title)).toEqual(['Close the game first']);
    expect(toBuildPlan({ ...base, tool: 'Tool', needs_allow: true, files: [], packs: [] }).steps[0]!.title).toBe('Ask before running Tool');
  });
});

describe('builds adapter: over the gateway', () => {
  it('reads the report with the mods page for ids, previews, and accepts by path id', async () => {
    const { api, asked } = await engine({
      mods: () => page, builds: () => built, builds_preview: () => ({ state: 'current', blocked: '', detail: '', tool: '', needs_allow: false, problem: '', files: [], packs: [], reasons: [] }),
      builds_accept_dropped: () => ({ id: 'd1' }),
    });
    const r = await api.getBuild(PROFILE);
    expect(r.dropped[0]!.modId).toBe(B);
    await api.previewBuild(PROFILE);
    expect(await api.acceptDropped(PROFILE, 'd1')).toEqual({ message: 'Playing without it' });
    expect(asked()).toContainEqual(['builds_accept_dropped', { profile: PROFILE, dropped_id: 'd1' }]);
    expect(asked()).toContainEqual(['builds', { profile: PROFILE }]);
  });

  it('leaves the choices not connected', async () => {
    const { api } = await engine({});
    await expect(api.searchPieces(PROFILE, 'x')).rejects.toMatchObject({ code: 'not_wired' });
    await expect(api.setRule(PROFILE, 'text', null)).rejects.toMatchObject({ code: 'not_wired' });
  });
});
