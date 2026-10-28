import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { connectEngine, resetEngineState } from '@/data/engine';
import { GatewayError } from '../transport';
import { createGateway } from '../hub';
import { createGatewayApi } from '../gatewayApi';
import { fakeTransport, flush } from '../fakeTransport.test-util';
import type { SaveCopy } from '../../types';

beforeEach(() => resetEngineState());
afterEach(() => resetEngineState());

type Handler = (params: Record<string, unknown> | undefined) => unknown;
/** An operation that starts a job ending as given, a moment after the start call answers. */
interface JobSpec { job: string; title: string; result?: unknown; undo?: Record<string, unknown>; error?: { code: string; message: string } }

/** A ready engine whose operations are answered by `ops`. A handler may throw a GatewayError (a refusal). */
async function engine(ops: Record<string, Handler | JobSpec>) {
  const t = fakeTransport({ state: 'ready', epoch: 1 });
  const g = createGateway(t);
  connectEngine(g, new QueryClient());
  await flush(); await flush();
  const base = t.call.bind(t);
  let seq = 0;
  t.call = (async (op: string, params?: Record<string, unknown>, o?: { epoch?: number }) => {
    const h = ops[op];
    if (!h) return base(op, params, o);
    t.calls.push({ operation: op, params, epoch: o?.epoch });
    if (typeof h === 'function') return h(params);
    setTimeout(() => {
      t.event({ seq: ++seq, type: 'started', job_id: h.job, data: { title: h.title, quiet: true } });
      if (h.error) t.event({ seq: ++seq, type: 'failed', job_id: h.job, data: { error: h.error } });
      else t.event({ seq: ++seq, type: 'finished', job_id: h.job, data: { result: h.result, undo: h.undo ?? null } });
    }, 0);
    return { job_id: h.job };
  }) as typeof t.call;
  return { t, api: createGatewayApi(g), asked: () => t.calls.map((c) => [c.operation, c.params]) };
}

const SAVE = 'C:\\saves\\ER0000.sl2';
const BAK = 'C:\\saves\\bk\\ER0000.sl2.1.bak';
const FOLDER = 'C:\\saves';
const LIB_ID = 'lib:abc123abc123:C:\\saves';
const stamp = [[1, 2], [3, 4]];
const undo = { type: 'save-restore', save: SAVE, backup: BAK };
const info = (over: Record<string, unknown> = {}) => ({
  path: SAVE, name: 'ER0000.sl2', kind: 'Standard', modified: '2026-10-27T14:02:00', block: 'OK', error: null, needs_repair: false,
  characters: [{ slot: 2, name: 'Ash', level: 45, body: 'Type A', where: 'Limgrave', runes: 1200, ok: true }],
  unreadable: [{ slot: 3, name: '', level: 0, ver: 1, error: 'A layout Bayle cannot read.' }],
  checksum_fixes: { slots: [], ud10: false }, loading_plan: [], ...over,
});

describe('saves adapter: reads', () => {
  it('lists live saves with path ids and ten slots', async () => {
    const { api, asked } = await engine({ saves: () => ({ infos: [info({ needs_repair: true })], libraries: {}, backups: [] }) });
    const s = (await api.listSaves('eldenring'))[0]!;
    expect(asked()).toEqual([['saves', undefined]]);
    expect(s).toMatchObject({ id: SAVE, fileName: 'ER0000.sl2', health: 'repair', source: 'Standard' });
    expect(s.slots).toHaveLength(10);
    expect(s.slots[1]).toMatchObject({ n: 2, character: { name: 'Ash', level: 45, location: 'Limgrave', runesHeld: 1200 } });
    expect(s.slots[2]).toEqual({ n: 3, problem: 'A layout Bayle cannot read.' });
  });

  it('lists Library copies (folder + entry id) and backups (path), reading each backup sheet', async () => {
    const { api, asked } = await engine({
      saves: () => ({
        infos: [],
        libraries: { [FOLDER]: { entries: [{ id: 'abc123abc123', name: 'Before DLC', from: 'ER0000.sl2', added: '2026-10-20T10:00:00', size: 2097152, characters: [{ slot: 1, name: 'Ash', level: 30, seconds: 7200 }] }] } },
        backups: [{ path: BAK, save_name: 'ER0000.sl2', when: '2026-10-26 09:30:00', action: 'Before a repair', size: 1048576, keep: true, mtime: 1 }],
      }),
      saves_sheet: () => ({ data: info() }),
    });
    const [lib, bak] = (await api.listCopies('eldenring')) as [SaveCopy, SaveCopy];
    expect(lib).toMatchObject({ id: LIB_ID, kind: 'library', name: 'Before DLC', size: '2.0 MB', slots: [{ n: 1, character: { name: 'Ash', playtime: '2.0 h' } }] });
    expect(bak).toMatchObject({ id: BAK, kind: 'backup', note: 'Before a repair', pinned: true, size: '1.0 MB' });
    expect(bak.slots.map((s) => s.n)).toEqual([2]);
    expect(asked()).toContainEqual(['saves_sheet', { path: BAK, slot: 1 }]);
  });

  it('lists a backup without characters when its sheet cannot be read', async () => {
    const { api } = await engine({
      saves: () => ({ infos: [], libraries: {}, backups: [{ path: 'b', save_name: 'x', when: 'bad', action: 'a', size: 5, keep: false, mtime: 1 }] }),
      saves_sheet: () => { throw new GatewayError({ code: 'not_found', message: 'no' }); },
    });
    expect((await api.listCopies('g'))[0]).toMatchObject({ slots: [], pinned: false, when: 'bad' });
  });
});

describe('saves adapter: writes with a stamp', () => {
  it('repairs: reads the plan, checks the ticked keys, then starts with the stamp; the entry comes from the job', async () => {
    const { api, asked } = await engine({
      saves_sheet: () => ({ data: info({ loading_plan: [{ slot: 1, issues: ['torrent'] }], checksum_fixes: { slots: [2], ud10: true } }) }),
      saves_check_repair: () => ({ info: info(), keys: [], stamp }),
      saves_repair: { job: 'j1', title: 'Repairing ER0000.sl2...', result: { file: 'ER0000.sl2', save: SAVE, backup: BAK, undo }, undo },
    });
    const r = await api.repairSave(SAVE);
    const keys = [['loading', 1, 'torrent'], ['checksum', 2], ['checksum', 'ud10']];
    expect(asked().slice(1)).toEqual([
      ['saves_check_repair', { path: SAVE, keys }],
      ['saves_repair', { path: SAVE, keys, expect: stamp }],
    ]);
    expect(r).toMatchObject({ message: 'Repaired ER0000.sl2', entry: { id: 'j1', kind: 'save', title: 'Repairing ER0000.sl2...', undoable: true } });
  });

  it('says so when a save has nothing to repair, without writing', async () => {
    const { api, asked } = await engine({ saves_sheet: () => ({ data: info() }) });
    await expect(api.repairSave(SAVE)).rejects.toMatchObject({ code: 'nothing_to_repair' });
    expect(asked().map((c) => c[0])).toEqual(['saves_sheet']);
  });

  it("refuses a stale write: the engine's refusal reaches the caller", async () => {
    const { api } = await engine({
      saves_check_restore_backup: () => ({ backup: {}, target: SAVE, stamp }),
      saves_restore_backup: () => { throw new GatewayError({ code: 'stale', message: 'A file changed since you were asked. Ask again.' }); },
    });
    await expect(api.restoreCopy(BAK, SAVE)).rejects.toMatchObject({ code: 'stale', message: 'A file changed since you were asked. Ask again.' });
  });

  it("turns a failed job into the engine's error", async () => {
    const { api } = await engine({ saves_back_up: { job: 'j2', title: 'Backing up saves...', error: { code: 'busy', message: 'The game is running.' } } });
    await expect(api.backupNow('eldenring')).rejects.toMatchObject({ code: 'busy', message: 'The game is running.' });
  });

  it('restores a backup: check with backup + target, then restore with the stamp', async () => {
    const { api, asked } = await engine({
      saves_check_restore_backup: () => ({ backup: {}, target: SAVE, stamp }),
      saves_restore_backup: { job: 'j3', title: 'Restoring ER0000.sl2...', result: { file: 'ER0000.sl2', save: SAVE, backup: BAK, undo }, undo },
    });
    const r = await api.restoreCopy(BAK, SAVE);
    expect(asked()).toEqual([
      ['saves_check_restore_backup', { backup: BAK, target: SAVE }],
      ['saves_restore_backup', { backup: BAK, target: SAVE, expect: stamp }],
    ]);
    expect(r).toMatchObject({ message: 'Restored ER0000.sl2', entry: { id: 'j3', undoable: true } });
  });

  it('restores a Library copy by folder and entry id', async () => {
    const { api, asked } = await engine({
      saves_check_replace_from_library: () => ({ rows: [], stamp }),
      saves_replace_from_library: { job: 'j4', title: 'Replacing a save...', result: { file: 'ER0000.sl2', source: 'x', save: SAVE, backup: BAK, undo }, undo },
    });
    await api.restoreCopy(LIB_ID, SAVE);
    expect(asked()).toEqual([
      ['saves_check_replace_from_library', { folder: FOLDER, entry_id: 'abc123abc123', target: SAVE }],
      ['saves_replace_from_library', { folder: FOLDER, entry_id: 'abc123abc123', target: SAVE, expect: stamp }],
    ]);
  });

  it('copies a character out of a live save (1-based slots) and words the result', async () => {
    const { api, asked } = await engine({
      saves_check_copy_character: () => ({ plan: {}, source: 'S', target: SAVE, same_file: false, stamp }),
      saves_copy_character: { job: 'j5', title: 'Copying a character...', result: { character: 'Ash', slot: 4, file: 'ER0000.sl2', save: SAVE, backup: BAK, undo }, undo },
    });
    const r = await api.copyCharacter({ saveId: 'S', n: 2 }, { saveId: SAVE, n: 4 });
    expect(asked()).toEqual([
      ['saves_check_copy_character', { source: 'S', src_slot: 2, target: SAVE, dst_slot: 4 }],
      ['saves_copy_character', { source: 'S', src_slot: 2, target: SAVE, dst_slot: 4, expect: stamp }],
    ]);
    expect(r).toMatchObject({ message: 'Ash is in slot 4 of ER0000.sl2', entry: { id: 'j5', undoable: true } });
  });

  it("copies a character out of a Library copy through the copy's file path", async () => {
    const file = 'C:\\saves\\library\\abc.sl2';
    const { api, asked } = await engine({
      saves_copy_entry: () => ({ name: 'n', path: file, changed_outside: false }),
      saves_check_copy_character: () => ({ stamp }),
      saves_copy_character: { job: 'j6', title: 'Copying a character...', result: { character: 'Ash', slot: 1, file: 'f' } },
    });
    await api.copyCharacter({ copyId: LIB_ID, n: 1 }, { saveId: SAVE, n: 1 });
    expect(asked()[0]).toEqual(['saves_copy_entry', { folder: FOLDER, entry_id: 'abc123abc123' }]);
    expect(asked()[1]![1]).toMatchObject({ source: file });
  });

  it("copies a character out of a backup through the backup's path", async () => {
    const { api, asked } = await engine({
      saves_check_copy_character: () => ({ stamp }),
      saves_copy_character: { job: 'j6b', title: 'Copying a character...', result: { character: 'Ash', slot: 1, file: 'f' } },
    });
    await api.copyCharacter({ copyId: BAK, n: 3 }, { saveId: SAVE, n: 1 });
    expect(asked()[0]).toEqual(['saves_check_copy_character', { source: BAK, src_slot: 3, target: SAVE, dst_slot: 1 }]);
  });

  it('keeps a copy, imports a file and backs up everything as jobs', async () => {
    const { api, asked } = await engine({
      saves_save_copy: { job: 'j7', title: 'Saving a copy...', result: { source: SAVE, entry_id: 'e', name: 'Mine' } },
      saves_import_files: { job: 'j8', title: 'Importing...', result: { imported: [{ file: 'f', entry_id: 'e', name: 'Old run' }], failed: [{ file: 'g', code: 'not_a_save' }] } },
      saves_back_up: { job: 'j9', title: 'Backing up saves...', result: { saves: ['a', 'b'], backups: ['x', 'y'] } },
    });
    expect(await api.keepCopy(SAVE, 'Mine')).toMatchObject({ message: 'Kept a copy as Mine', entry: { id: 'j7', undoable: false } });
    expect(await api.importSave('eldenring', 'C:\\old.sl2')).toMatchObject({ message: 'Imported Old run', detail: '1 file could not be imported.', entry: { id: 'j8' } });
    expect(await api.backupNow('eldenring')).toMatchObject({ message: 'Backed up 2 saves', entry: { id: 'j9' } });
    expect(asked()).toEqual([
      ['saves_save_copy', { path: SAVE, name: 'Mine' }],
      ['saves_import_files', { files: ['C:\\old.sl2'] }],
      ['saves_back_up', { everything: true }],
    ]);
  });
});

describe('saves adapter: quick writes (no entry)', () => {
  it('renames a Library copy', async () => {
    const { api, asked } = await engine({ saves_rename_copy: () => ({ text: 'New name' }) });
    const r = await api.renameCopy(LIB_ID, 'New name');
    expect(asked()).toEqual([['saves_rename_copy', { folder: FOLDER, entry_id: 'abc123abc123', name: 'New name' }]]);
    expect(r).toEqual({ message: 'Renamed to New name' });
  });

  it('removes a Library copy: the check gives the name, the removal confirms it', async () => {
    const { api, asked } = await engine({ saves_check_remove_copy: () => ({ text: 'Before DLC' }), saves_remove_copy: () => ({ text: '' }) });
    expect(await api.removeCopy(LIB_ID)).toEqual({ message: 'Removed Before DLC' });
    expect(asked()[1]).toEqual(['saves_remove_copy', { folder: FOLDER, entry_id: 'abc123abc123', expect: 'Before DLC' }]);
  });

  it('removes a backup: the check gives its stamp, the delete confirms it', async () => {
    const { api, asked } = await engine({ saves_check_delete_backup: () => ({ path: BAK, save_name: 'ER0000.sl2', stamp: [10, 20.5] }), saves_delete_backup: () => ({ text: '' }) });
    expect(await api.removeCopy(BAK)).toMatchObject({ message: 'Removed the backup of ER0000.sl2' });
    expect(asked()[1]).toEqual(['saves_delete_backup', { backup: BAK, expect: [10, 20.5] }]);
  });

  it('refuses a stale removal', async () => {
    const { api } = await engine({
      saves_check_remove_copy: () => ({ text: 'A' }),
      saves_remove_copy: () => { throw new GatewayError({ code: 'stale', message: 'That copy changed since you were asked. Ask again.' }); },
    });
    await expect(api.removeCopy(LIB_ID)).rejects.toMatchObject({ code: 'stale' });
  });

  it('keeps and releases a backup', async () => {
    const { api, asked } = await engine({ saves_keep_backup: () => ({ text: '' }) });
    await api.pinBackup(BAK, true);
    await api.pinBackup(BAK, false);
    expect(asked().map((c) => c[1])).toEqual([{ backup: BAK, keep: true }, { backup: BAK, keep: false }]);
  });
});

describe('saves adapter: left not connected', () => {
  it('keeps the features the engine cannot do yet, with the usual not-connected error and no engine call', async () => {
    const { api, asked } = await engine({});
    await expect(api.deleteCharacter(SAVE, 1)).rejects.toMatchObject({ code: 'not_wired' });
    await expect(api.renameCopy(BAK, 'n')).rejects.toMatchObject({ code: 'not_wired' });
    expect(asked()).toEqual([]);
  });
});
