/**
 * Sample data for the mock backend. Mirrors the HTML prototype so every
 * screen has something real-looking to show. Not used in production.
 */
import type {
  ActivityEntry, BuildReport, ConfigFile, PieceHit, Game, Mod, ModFile, OverhaulSetup, Profile, SaveCopy, SaveFile, Settings, SetupFile, Slot,
} from '../types';

type ModTemplate = Omit<Mod, 'id' | 'packageId' | 'enabled' | 'loadAfter'> & Partial<Pick<Mod, 'loadAfter'>>;

const TPL: Record<string, ModTemplate> = {
  'seamless-coop': { name: 'Seamless Co-op', kind: 'package', tags: [{ label: 'Shared', tone: 'info' }], description: 'Used by 2 profiles · installed Sep 12', folder: 'library/SeamlessCoop/1.8.4', size: '24 MB', version: '1.8.4', addedOn: 'Sep 12', configs: ['ersc_settings.ini'], shared: true },
  'detailed-item-descriptions': { name: 'Detailed Item Descriptions', kind: 'package', tags: [], description: 'Changes item text · included in the merged game data', folder: 'mods/DetailedItemDescriptions', size: '0.4 MB', version: '3.1', addedOn: 'Sep 20', configs: [], loadAfter: [{ packageId: 'seamless-coop', optional: true }] },
  'clevers-moveset': { name: "Clever's Moveset Modpack", kind: 'package', tags: [], description: 'New movesets for 40 weapons', overriddenBy: 'convergence', overriddenFiles: 3, folder: 'mods/CleversMoveset', size: '310 MB', version: '1.4', addedOn: 'Oct 2', configs: [] },
  'unlock-fps': { name: 'Unlock the FPS', kind: 'package', tags: [], description: 'Raises the frame cap', folder: 'mods/UnlockTheFPS', size: '0.1 MB', version: '2.0', addedOn: 'Aug 30', configs: ['config.toml'] },
  'grand-merchant': { name: 'Grand Merchant', kind: 'package', tags: [], description: 'One merchant who sells everything', folder: 'mods/GrandMerchant', size: '3 MB', version: '1.2', addedOn: 'yesterday', configs: [] },
  convergence: { setupId: 'convergence', name: 'Convergence', kind: 'package', staysLast: true, tags: [{ label: 'Loads last', tone: 'vio' }], description: 'Loads last, built on top of the mods above it', folder: 'mods/Convergence', size: '1.9 GB', version: '2.3', addedOn: 'Sep 12', configs: ['Convergence.ini', 'README.md'], rebuildFile: 'regulation.bin',
    update: { version: '2.4', releasedOn: 'Oct 20', changes: [{ family: 'params', count: 212, unit: 'parameter rows' }, { family: 'text', count: 40, unit: 'text lines' }, { family: 'animations', count: 6, unit: 'animations' }], touchesPicks: 1, newClashes: 2, notes: 'Rebalances daggers and adds the Carian Needle questline.' } },
  revive: { setupId: 'revive', name: 'Nightreign Revive', kind: 'package', staysLast: true, tags: [{ label: 'Loads last', tone: 'vio' }], description: 'A co-op revive system. Loads last, built on top of the mods above it', folder: 'revive', size: '640 MB', version: '1.4', addedOn: 'today', configs: ['revive.ini'], rebuildFile: 'regulation.bin' },
  'revive-dll': { name: 'Nightreign Revive', file: 'NightreignRevive.dll', nameSource: 'install', partOfModId: 'revive', kind: 'native', partOfSetupId: 'revive', tags: [{ label: 'Loads early' }], description: 'Starts early, loads after the other natives', folder: 'revive/NightreignRevive.dll', size: '4 MB', addedOn: 'today', configs: [], native: { loadEarly: true, optional: false, initializer: { kind: 'function', value: 'ReviveInit' }, finalizer: '' } },
  randomizer: { name: 'Item and Enemy Randomizer', kind: 'package', tags: [{ label: 'Managed', tone: 'info' }], description: 'Seed 48211 · made by the randomizer tool', folder: 'mods/randomizer', size: '820 MB', version: '0.9', addedOn: 'Oct 5', configs: [] },
  ersc: { name: 'Seamless Co-op', file: 'ersc.dll', nameSource: 'install', partOfModId: 'seamless-coop', fileDetails: { product: 'Seamless Co-op', description: 'ersc' }, kind: 'native', tags: [{ label: 'Loads early' }], description: 'Starts before the game sets itself up', folder: 'mods/SeamlessCoop/ersc.dll', size: '3 MB', addedOn: 'Sep 12', configs: ['launcher.txt'], native: { loadEarly: true, optional: false, initializer: { kind: 'function', value: 'ModInit' }, finalizer: '', afterUpdate: 'ok' } },
  eml: { name: 'Elden Mod Loader', file: 'EldenModLoader.dll', nameSource: 'known', kind: 'native', tags: [{ label: 'Optional' }], description: 'Loads other DLL mods from its own folder. The game starts without it', folder: 'mods/EldenModLoader/EldenModLoader.dll', size: '1 MB', addedOn: 'Sep 14', configs: [], native: { loadEarly: false, optional: true, initializer: { kind: 'none', value: '' }, finalizer: '', afterUpdate: 'may-fail' } },
  pause: { name: 'PauseTheGame.dll', file: 'PauseTheGame.dll', nameSource: 'file', kind: 'native', tags: [{ label: 'No folder', tone: 'warn' }], description: "This DLL isn't in a folder of its own", folder: 'mods/PauseTheGame.dll', size: '0.1 MB', addedOn: 'Aug 1', configs: [], native: { loadEarly: false, optional: false, initializer: { kind: 'none', value: '' }, finalizer: '', afterUpdate: 'unknown' } },
  'nr-coop': { name: 'Nightreign Seamless', kind: 'package', tags: [{ label: 'Shared', tone: 'info' }], description: 'Co-op without matchmaking', folder: 'library/NightreignSeamless/0.6', size: '18 MB', version: '0.6', addedOn: 'Sep 30', configs: ['nrsc_settings.ini'], shared: true },
  'nr-solo': { name: 'Solo Scaling', kind: 'package', tags: [], description: 'Balances expeditions for one player', folder: 'mods/SoloScaling', size: '2 MB', version: '1.1', addedOn: 'Oct 3', configs: [] },
  nrsc: { name: 'Nightreign Seamless', file: 'nrsc.dll', nameSource: 'install', partOfModId: 'nr-coop', fileDetails: { product: 'Nightreign Seamless' }, kind: 'native', tags: [{ label: 'Loads early' }], description: 'Starts before the game sets itself up', folder: 'mods/NightreignSeamless/nrsc.dll', size: '2 MB', addedOn: 'Sep 30', configs: [], native: { loadEarly: true, optional: false, initializer: { kind: 'none', value: '' }, finalizer: '' } },
};

const M = (id: string, o: Partial<Mod> = {}): Mod => {
  const t = TPL[id];
  if (!t) throw new Error(`unknown mod template ${id}`);
  return structuredClone({ id, packageId: id, enabled: true, loadAfter: [], ...t, ...o }) as Mod;
};

export const games: Game[] = [
  { id: 'er', name: 'Elden Ring', abbr: 'ER', supported: true, build: '1.16.1', lastRunBuild: '1.16.0', activeProfileId: 'er-sc', lastPlayed: 'last played today, 00:38', slotsPerSave: 10 },
  { id: 'nr', name: 'Nightreign', abbr: 'NR', supported: true, build: '1.2.0', lastRunBuild: '1.2.0', activeProfileId: 'nr-coop', lastPlayed: 'last played Oct 19', slotsPerSave: 1 },
  { id: 'ds3', name: 'Dark Souls III', abbr: 'DS3', supported: false, installFolder: 'D:\\SteamLibrary\\steamapps\\common\\DARK SOULS III\\Game', slotsPerSave: 10 },
  { id: 'sek', name: 'Sekiro', abbr: 'SEK', supported: false, slotsPerSave: 10 },
];

const prof = (p: Omit<Profile, 'modCount' | 'enabledCount'>): Profile => ({ ...p, modCount: p.mods.length, enabledCount: p.mods.filter((m) => m.enabled).length });

export const profiles: Profile[] = [
  prof({ id: 'er-sc', gameId: 'er', name: 'Seamless + Convergence', saveId: 'coop', merge: 'needs', onlineAccepted: false,
    mods: [M('seamless-coop'), M('detailed-item-descriptions'), M('clevers-moveset'), M('unlock-fps', { enabled: false }), M('grand-merchant', { missing: true }), M('convergence'), M('ersc'), M('eml'), M('pause', { enabled: false })] }),
  prof({ id: 'er-qol', gameId: 'er', name: 'Vanilla + QoL', saveId: 'std', merge: 'none', onlineAccepted: false, outsidePath: 'D:\\Games\\ER mods\\vanilla-qol', strays: ['old_Convergence_2.2', 'PauseTheGame'],
    mods: [M('detailed-item-descriptions', { loadAfter: [] }), M('unlock-fps'), M('grand-merchant')] }),
  prof({ id: 'er-rnd', gameId: 'er', name: 'Randomizer run', saveId: 'rnd', merge: 'none', onlineAccepted: false, mods: [M('randomizer'), M('eml')] }),
  prof({ id: 'er-rev', gameId: 'er', name: 'Revive co-op', saveId: 'coop', merge: 'ok', onlineAccepted: false,
    installer: {
      name: 'Nightreign Revive',
      entries: [{ title: "Revive's game files", detail: 'NightreignRevive\\mod' }, { title: 'NightreignRevive.dll', detail: 'set to start early' }, { title: 'revive_loader.dll', detail: "the installer's own loader, not needed with me3" }],
      settings: [{ title: 'Online play turned off', detail: 'start_online = false · undone' }, { title: 'Its own save file', detail: "ER0000_revive.co2 holds your Revive characters, so it stays this profile's save", kept: true }],
      leftovers: [{ title: 'revive_backup folder', detail: 'in the game folder · 412 MB' }, { title: 'installation.json', detail: "the installer's record" }, { title: 'dinput8.dll.bak', detail: 'a backup in the game folder' }],
    },
    mods: [M('seamless-coop'), M('revive', { installerMade: true, tags: [{ label: 'Installer-made', tone: 'warn' }, { label: 'Loads last', tone: 'vio' }] }), M('ersc'), M('revive-dll', { installerMade: true, tags: [{ label: 'Installer-made', tone: 'warn' }] })] }),
  prof({ id: 'er-pie', gameId: 'er', name: "PieGuy's Co-op Pack", saveId: 'coop', merge: 'none', onlineAccepted: false, mods: [M('seamless-coop'), M('grand-merchant'), M('detailed-item-descriptions'), M('ersc'), M('pause')] }),
  prof({ id: 'nr-coop', gameId: 'nr', name: 'Nightreign co-op', merge: 'none', onlineAccepted: false, saveId: 'nrstd', mods: [M('nr-coop'), M('nr-solo', { enabled: false }), M('nrsc')] }),
  prof({ id: 'nr-plus', gameId: 'nr', name: 'Nightreign vanilla+', merge: 'none', onlineAccepted: false, saveId: 'nrstd', mods: [M('nr-solo')] }),
];

/* ------------------------------------------------------------------ files inside each mod */

const LANGS = ['engus', 'jpnjp', 'frafr', 'deude', 'itait', 'spaes', 'polpl', 'porbr', 'zhocn'];
const LANG_NAME: Record<string, string> = { engus: 'English', jpnjp: 'Japanese', frafr: 'French', deude: 'German', itait: 'Italian', spaes: 'Spanish', polpl: 'Polish', porbr: 'Portuguese', zhocn: 'Chinese' };
const pad = (n: number, w = 2) => String(n).padStart(w, '0');

export function reviveSetupFiles(): SetupFile[] {
  const f: SetupFile[] = [
    { path: 'mod\\regulation.bin', what: "the game's rules", action: 'combine', needed: true },
    { path: 'mod\\chr\\c0000.anibnd.dcx', what: 'player animations', action: 'merge', needed: true },
  ];
  for (let i = 1; i < 200; i++) f.push({ path: `mod\\chr\\c${pad(2000 + i * 10, 4)}.anibnd.dcx`, what: 'enemy animations', action: 'merge' });
  f.push({ path: 'mod\\sfx\\sfxbnd_commoneffects.ffxbnd.dcx', what: 'effects', action: 'merge' }, { path: 'mod\\sfx\\sfxbnd_revive.ffxbnd.dcx', what: 'the revive effect', action: 'merge' }, { path: 'mod\\parts\\wp_revive_totem.partsbnd.dcx', what: 'a new item model', action: 'copy' });
  for (let i = 0; i < 21; i++) f.push({ path: `mod\\parts\\am_m_${1100 + i * 10}.partsbnd.dcx`, what: 'armour model', action: 'copy' });
  f.push({ path: 'mod\\script\\talk\\m00_00_00_00.talkesdbnd.dcx', what: 'the grace menu script', action: 'place', target: 'script\\talk\\m00_00_00_00.talkesdbnd.dcx', needed: true });
  LANGS.forEach((l) => f.push({ path: `mod\\msg\\${l}\\revive_menu.json`, what: `menu text, ${LANG_NAME[l]}`, action: 'text' }));
  f.push({ path: 'revive.ini', what: 'its settings', action: 'keep' }, { path: 'README.txt', what: 'readme', action: 'leave' }, { path: 'NightreignRevive_Installer.exe', what: 'its own installer', action: 'leave' });
  return f;
}

export function modFiles(m: Mod): ModFile[] {
  if (m.missing) return [];
  const f: ModFile[] = [];
  const add = (path: string, what: string, x: Partial<ModFile> = {}) => f.push({ path, what, ...x });
  const many = (n: number, fn: (i: number) => void) => { for (let i = 0; i < n; i++) fn(i); };
  switch (m.id) {
    case 'seamless-coop': LANGS.forEach((l) => add(`msg\\${l}\\menu_dlc02.msgbnd.dcx`, 'co-op menu text')); add('menu\\hi\\01_common.sblytbnd.dcx', 'co-op menu layout'); add('ersc_settings.ini', 'password, scaling, invasions'); add('README.txt', 'how to play'); break;
    case 'detailed-item-descriptions': LANGS.forEach((l) => add(`msg\\${l}\\item_dlc02.msgbnd.dcx`, 'item text')); add('README.md', 'what changed'); break;
    case 'clevers-moveset': add('regulation.bin', "the game's rules"); many(46, (i) => add(`chr\\c0000_a${pad(i)}.anibnd.dcx`, 'weapon moveset', [0, 3, 12].includes(i) ? { clash: { tone: 'warn', note: "Convergence's copy wins" } } : {})); add('action\\script\\c0000.hks', 'combat script'); add('sfx\\sfxbnd_moveset.ffxbnd.dcx', 'effects'); add('Readme.pdf', 'how to use'); break;
    case 'unlock-fps': add('config.toml', 'frame cap and field of view'); add('README.md', 'how to use'); break;
    case 'convergence':
      add('regulation.bin', "the game's rules");
      many(1180, (i) => add(`chr\\c0000_a${pad(i)}.anibnd.dcx`, i < 46 ? 'weapon moveset' : 'animations', [0, 3, 12].includes(i) ? { clash: { tone: 'ok', note: "Also in Clever's · this one wins" } } : {}));
      many(860, (i) => add(`parts\\wp_a_${1000 + i}.partsbnd.dcx`, 'item model'));
      many(140, (i) => add(`sfx\\sfxbnd_c${4000 + i}.ffxbnd.dcx`, 'effects'));
      many(200, (i) => add(`map\\m60\\m60_${pad(40 + (i % 20))}_${pad(30 + Math.floor(i / 20))}_00.mapbnd.dcx`, 'map piece'));
      LANGS.forEach((l) => { add(`msg\\${l}\\item_dlc02.msgbnd.dcx`, 'item text'); add(`msg\\${l}\\menu_dlc02.msgbnd.dcx`, 'menu text'); });
      many(16, (i) => add(`script\\talk\\t${100 + i}00.talkesdbnd.dcx`, 'NPC dialogue'));
      add('Convergence.ini', 'difficulty, classes, extras'); add('README.md', 'install notes'); add('Changelog.txt', 'what changed');
      break;
    case 'revive': reviveSetupFiles().filter((x) => x.path.startsWith('mod\\')).forEach((x) => add(x.path.slice(4), x.what)); add('revive.ini', 'revive timer and rules'); break;
    case 'ersc': add('ersc.dll', 'the native me3 injects', { main: true }); add('launcher.txt', 'launch options'); add('logs\\ersc.log', 'what it wrote last run'); break;
    case 'eml': add('EldenModLoader.dll', 'the native me3 injects', { main: true }); add('mod_loader_config.ini', 'load delay'); add('logs\\mod_loader.log', 'what it wrote last run'); break;
    case 'revive-dll': add('NightreignRevive.dll', 'the native me3 injects', { main: true }); add('logs\\NightreignRevive.log', 'what it wrote last run'); break;
    case 'nrsc': add('nrsc.dll', 'the native me3 injects', { main: true }); add('nrsc_settings.ini', 'password and scaling'); break;
    default:
      if (m.kind === 'native') add(m.folder.split('/').pop() ?? m.name, 'the native me3 injects', { main: true });
      else { add('regulation.bin', "the game's rules"); add('README.txt', 'how to use'); }
  }
  return f;
}

/* ------------------------------------------------------------------ saves */

const ch = (n: number, name: string, level: number, location = 'Roundtable Hold', playtime = '40 h', extra: Partial<Slot> = {}): Slot => ({ n, character: { name, level, location, playtime, body: 'Type A', runesHeld: level * 9043, modItems: 'none' }, ...extra });

function fill(slots: Slot[], count: number): Slot[] {
  const out: Slot[] = [];
  for (let n = 1; n <= count; n++) out.push(slots.find((s) => s.n === n) ?? { n });
  return out;
}

export const saves: SaveFile[] = [
  { id: 'coop', gameId: 'er', label: 'Seamless Co-op', fileName: 'ER0000.co2', size: '28.9 MB', health: 'repair', source: 'Seamless Co-op', sourceDetail: 'Made by Seamless Co-op (save_file_extension = co2 in ersc_settings.ini).', usedBy: ['Seamless + Convergence', 'Revive co-op', "PieGuy's Co-op Pack"],
    slots: fill([ch(1, "Marika's Faithful", 142, 'Farum Azula', '85 h', { problem: 'Character data is out of step. The game may refuse this character.' }), ch(2, 'Co-op Bonk', 91, 'Roundtable Hold', '55 h'), ch(4, 'Old Alt', 12, 'Roundtable Hold', '7 h', { stale: true }), ch(5, 'Bleed Build', 150, 'Roundtable Hold', '90 h'), ch(6, 'Glintstone Sage', 120, 'Leyndell', '72 h'), ch(7, 'Duelist 125', 125, 'Farum Azula', '75 h'), ch(9, 'NG+7 Run', 200, 'Roundtable Hold', '120 h'), ch(10, 'Dex Test', 80, 'Liurnia', '48 h')], 10) },
  { id: 'std', gameId: 'er', label: 'Standard', fileName: 'ER0000.sl2', size: '28.6 MB', health: 'ok', source: 'Game default', sourceDetail: "The game's own save. Launch Offline and Vanilla always use it.", usedBy: ['Vanilla + QoL', 'Offline', 'Vanilla'],
    slots: fill([ch(1, "Marika's Faithful", 142, 'Farum Azula', '85 h'), ch(2, 'Bonk', 88, 'Roundtable Hold', '52 h')], 10) },
  { id: 'rnd', gameId: 'er', label: 'Randomizer run', fileName: 'ER0000_rando.sl2', size: '27.9 MB', health: 'ok', source: 'Profile save', sourceDetail: "Set by the profile Randomizer run (me3's savefile option), so the run never touches your main save.", usedBy: ['Randomizer run'],
    slots: fill([ch(1, 'Seed 48211', 34, 'Limgrave', '9 h'), ch(2, 'Seed 1907', 61, 'Caelid', '21 h')], 10) },
  { id: 'nrstd', gameId: 'nr', label: 'Standard', fileName: 'NR0000.sl2', size: '9.1 MB', health: 'ok', source: 'Game default', sourceDetail: "The game's own save.", usedBy: ['Nightreign co-op', 'Nightreign vanilla+'],
    slots: fill([ch(1, 'Wylder', 15, 'Roundtable Hold', '30 h')], 1) },
];

export const copies: SaveCopy[] = [
  { id: 'c1', gameId: 'er', kind: 'library', fromFile: 'ER0000.co2', name: 'Before Convergence 2.3', note: 'whole file', when: 'Oct 18, 21:04', slots: [ch(1, "Marika's Faithful", 139), ch(2, 'Bonk', 88)] },
  { id: 'c2', gameId: 'er', kind: 'library', fromFile: 'ER0000.sl2', name: 'Pre-DLC run', note: 'whole file', when: 'Sep 2, 10:12', slots: [ch(1, 'Marika the First', 71)] },
  { id: 'c3', gameId: 'er', kind: 'library', name: 'Twinkmaster', note: 'File missing. Only Remove works.', when: 'Jul 30', missing: true, slots: [] },
  { id: 'b1', gameId: 'er', kind: 'backup', fromFile: 'ER0000.co2', name: 'Today 00:41', note: 'after play', when: 'Today 00:41', size: '28.9 MB', slots: [ch(1, "Marika's Faithful", 142), ch(2, 'Co-op Bonk', 91), ch(4, 'Old Alt', 12)] },
  { id: 'b2', gameId: 'er', kind: 'backup', fromFile: 'ER0000.co2', name: 'Yesterday 19:02', note: 'before launch', when: 'Yesterday 19:02', size: '28.9 MB', pinned: true, slots: [ch(1, "Marika's Faithful", 141), ch(2, 'Co-op Bonk', 90)] },
  { id: 'b3', gameId: 'er', kind: 'backup', fromFile: 'ER0000.sl2', name: 'Oct 18 20:30', note: 'before repair', when: 'Oct 18 20:30', size: '28.6 MB', slots: [ch(1, "Marika's Faithful", 139), ch(2, 'Bonk', 86)] },
  { id: 'n1', gameId: 'nr', kind: 'library', fromFile: 'NR0000.sl2', name: 'First expedition', note: 'whole file', when: 'Oct 1, 22:10', slots: [ch(1, 'Wylder', 9)] },
];

/* ------------------------------------------------------------------ config files */

export const configFiles: Record<string, ConfigFile> = {
  coop: { id: 'coop', modId: 'seamless-coop', modName: 'Seamless Co-op', name: 'ersc_settings.ini', path: 'mods/SeamlessCoop/ersc_settings.ini', format: 'ini',
    sections: [
      { name: 'GAMEPLAY', fields: [
        { key: 'cooppassword', type: 'secret', value: 'tarnished-only', default: '', help: 'Friends type the same password to join your session.' },
        { key: 'allow_invaders', type: 'bool', value: true, default: false, help: 'Lets other players invade the session.' },
        { key: 'death_debuffs', type: 'bool', value: true, default: true, help: 'Rot of Pride applies on death.' },
        { key: 'allow_summons', type: 'bool', value: true, default: true },
        { key: 'skip_splash_screens', type: 'bool', value: false, default: false },
        { key: 'default_boot', type: 'readonly', value: 1, help: 'Only Edit as text can change this one.' },
      ] },
      { name: 'SCALING', note: "Per extra player; only the host's numbers count.", fields: [
        { key: 'enemy_health_scaling', type: 'int', value: 120, default: 100, unit: '%', help: '% per extra player.' },
        { key: 'enemy_damage_scaling', type: 'int', value: 0, default: 0, unit: '%' },
        { key: 'enemy_posture_scaling', type: 'int', value: 10, default: 10, unit: '%' },
        { key: 'boss_health_scaling', type: 'int', value: 100, default: 100, unit: '%' },
        { key: 'boss_damage_scaling', type: 'int', value: 0, default: 0, unit: '%' },
        { key: 'boss_posture_scaling', type: 'int', value: 10, default: 10, unit: '%' },
      ] },
      { name: 'SAVE', fields: [{ key: 'save_file_extension', type: 'string', value: 'co2', default: 'co2', help: "The co-op save's extension." }] },
      { name: 'LANGUAGE', fields: [{ key: 'mod_language_override', type: 'enum', value: '', default: '', help: 'Empty follows the game.', options: [{ value: '', label: 'Follow the game' }, { value: 'english', label: 'English' }, { value: 'italian', label: 'Italiano' }, { value: 'japanese', label: '日本語' }] }] },
    ],
    text: '[GAMEPLAY]\ncooppassword = tarnished-only\nallow_invaders = 1\ndeath_debuffs = 1\nallow_summons = 1\nskip_splash_screens = 0\ndefault_boot = 1\n\n[SCALING]\nenemy_health_scaling = 120\nenemy_damage_scaling = 0\nenemy_posture_scaling = 10\nboss_health_scaling = 100\nboss_damage_scaling = 0\nboss_posture_scaling = 10\n\n[SAVE]\nsave_file_extension = co2\n\n[LANGUAGE]\nmod_language_override =\n' },
  ini: { id: 'ini', modId: 'convergence', modName: 'Convergence', name: 'Convergence.ini', path: 'mods/Convergence/Convergence.ini', format: 'ini',
    sections: [
      { name: 'General', fields: [
        { key: 'AutoSave', type: 'bool', value: false, default: true, help: 'Saves after every area change.' },
        { key: 'StartingClass', type: 'enum', value: 'Random', default: 'Random', options: [{ value: 'Random', label: 'Random' }, { value: 'Vagabond', label: 'Vagabond' }, { value: 'Astrologer', label: 'Astrologer' }] },
      ] },
      { name: 'Difficulty', fields: [{ key: 'Multiplier', type: 'float', value: 1.0, default: 1.0 }] },
    ],
    text: '[General]\nAutoSave = 0\nStartingClass = Random\n\n[Difficulty]\nMultiplier = 1.0\n' },
  md: { id: 'md', modId: 'convergence', modName: 'Convergence', name: 'README.md', path: 'mods/Convergence/README.md', format: 'markdown',
    text: '# Convergence 2.3\n\nThank you for downloading The Convergence.\n\nInstall with me3 and set it as an overhaul; this launcher does that for you.\n\n## Known issues\n\n- regulation.bin must be rebuilt after changing any other parameter pack.\n' },
  toml: { id: 'toml', modId: 'unlock-fps', modName: 'Unlock the FPS', name: 'config.toml', path: 'mods/UnlockTheFPS/config.toml', format: 'toml',
    sections: [{ name: 'fps', fields: [{ key: 'cap', type: 'int', value: 144, default: 60 }, { key: 'vsync', type: 'bool', value: true, default: true }] }],
    text: '[fps]\ncap = 144\nvsync = true\n' },
  txt: { id: 'txt', modId: 'ersc', modName: 'Seamless Co-op', groupId: 'seamless-coop', viaFile: 'ersc.dll', name: 'launcher.txt', path: 'mods/SeamlessCoop/launcher.txt', format: 'text', text: '// ersc.dll launcher notes\nload_early=1\n' },
  nrsc: { id: 'nrsc', modId: 'nr-coop', modName: 'Nightreign Seamless', name: 'nrsc_settings.ini', path: 'library/NightreignSeamless/nrsc_settings.ini', format: 'ini',
    sections: [{ name: 'GAMEPLAY', fields: [{ key: 'password', type: 'secret', value: 'nightlord', default: '', help: 'Friends type the same password to join.' }] }],
    text: '[GAMEPLAY]\npassword = nightlord\n' },
};
/** Which config file id a mod's attached file name maps to. Unknown files get a generated text file. */
export const configIdByName: Record<string, string> = { 'ersc_settings.ini': 'coop', 'Convergence.ini': 'ini', 'README.md': 'md', 'config.toml': 'toml', 'launcher.txt': 'txt', 'nrsc_settings.ini': 'nrsc' };

/* ------------------------------------------------------------------ overhaul setups */

export const setups: Record<string, OverhaulSetup> = {
  convergence: { id: 'convergence', name: 'Convergence', version: '2.3', savedOn: 'Sep 12', gameDir: 'Convergence\\', languages: 0, recipe: { source: 'yours', forVersion: '2.3', check: 'match', base: 'vanilla' },
    dlls: [{ name: 'Convergence.dll', loadEarly: true, loadAfterOthers: true, initFunction: 'ConvergenceInit' }],
    files: [
      { path: 'regulation.bin', what: "the game's rules", action: 'combine', needed: true },
      { path: 'chr\\c0000.anibnd.dcx', what: 'player animations', action: 'merge', needed: true },
      { path: 'msg\\engus\\item.msgbnd.dcx', what: 'item text', action: 'merge' },
      ...Array.from({ length: 40 }, (_, i): SetupFile => ({ path: `parts\\wp_a_${1000 + i}.partsbnd.dcx`, what: 'weapon model', action: 'copy' })),
      { path: 'Convergence.ini', what: 'its settings', action: 'keep' },
      { path: 'README.md', what: 'readme', action: 'leave' },
    ] },
  revive: { id: 'revive', name: 'Nightreign Revive', version: '1.4', savedOn: null, gameDir: 'mod\\', ownInstaller: 'NightreignRevive_Installer.exe', languages: 9,
    recipe: { source: 'community', forVersion: '1.4', check: 'soft', base: 'vanilla', differences: ['settings\\strings_jpnjp.json is new; added as menu text', 'mod\\sfx\\sfxbnd_revive.ffxbnd.dcx is 2 MB larger'] },
    dlls: [{ name: 'NightreignRevive.dll', loadEarly: true, loadAfterOthers: true, initFunction: 'ReviveInit' }],
    files: reviveSetupFiles() },
};

/* ------------------------------------------------------------------ activity */

export const activity: ActivityEntry[] = [
  { id: 'a1', gameId: 'er', kind: 'launch', ok: true, title: 'Played Elden Ring', detail: 'Seamless + Convergence · saves repaired, 1 leftover process closed', day: 'Today', time: '00:38', duration: '2 h 11 min', hasLog: true, undoable: false, noUndoReason: 'A session cannot be undone' },
  { id: 'a2', gameId: 'er', kind: 'profile', ok: true, title: 'Turned off Unlock the FPS', detail: 'Seamless + Convergence', day: 'Today', time: '00:30', duration: 'under a second', hasLog: false, undoable: true, undoLines: ['Unlock the FPS is turned back on in Seamless + Convergence'] },
  { id: 'a3', gameId: 'er', kind: 'rebuild', ok: false, title: 'Rebuild combined parameters', detail: 'It did not finish. Details are in the log.', day: 'Yesterday', time: '22:15', duration: '14 s', hasLog: true, undoable: false },
  { id: 'a4', gameId: 'er', kind: 'install', ok: true, title: 'Installed Grand Merchant', detail: 'from GrandMerchant-1.2.zip · Seamless + Convergence', day: 'Yesterday', time: '21:50', duration: '3 s', hasLog: false, undoable: true, undoLabel: 'Undo install', undoLines: ['Grand Merchant leaves Seamless + Convergence', 'The files the install added are removed; any you changed since stay, and are listed'] },
  { id: 'a5', gameId: 'er', kind: 'save', ok: true, title: 'Backed up ER0000.co2', detail: 'before launch', day: 'Yesterday', time: '19:02', duration: '1 s', hasLog: false, undoable: false, noUndoReason: 'Backups cannot be taken back' },
  { id: 'a6', gameId: 'er', kind: 'profile', ok: true, title: 'Renamed profile Seamless Convergence to Seamless + Convergence', detail: '', day: 'Oct 18', time: '20:41', duration: 'under a second', hasLog: false, undoable: true, undoLabel: 'Undo rename', undoLines: ['The profile is called Seamless Convergence again'] },
  { id: 'a7', gameId: 'er', kind: 'install', ok: false, title: 'Imported into Seamless + Convergence', detail: 'A file was in use. Close the game and other programs using it, then try again.', day: 'Oct 18', time: '18:10', duration: '2 s', hasLog: true, undoable: false },
];

/* ------------------------------------------------------------------ settings */

export const defaultSettings: Settings = {
  paths: {
    games: { er: 'D:\\SteamLibrary\\steamapps\\common\\ELDEN RING\\Game', nr: 'D:\\SteamLibrary\\steamapps\\common\\ELDEN RING NIGHTREIGN\\Game' },
    me3: 'C:\\Users\\you\\AppData\\Local\\me3\\me3.exe',
    profiles: 'C:\\Users\\you\\AppData\\Local\\Carlomos7.Bayle\\profiles',
    sharedMods: 'D:\\Mods\\library',
    backups: 'C:\\Users\\you\\AppData\\Local\\Carlomos7.Bayle\\backups',
    logs: 'C:\\Users\\you\\AppData\\Local\\Carlomos7.Bayle\\logs',
    settingsFile: 'C:\\Users\\you\\AppData\\Local\\Carlomos7.Bayle\\settings.json',
  },
  launch: { autoRebuild: true, installOverhauls: true, bootBoost: true, showLogos: false, diagnostics: false, closeLeftoversBefore: true, closeLeftoversAfter: true, warnLeftovers: true, offlineSkipOverhaul: false, offlineStartSteam: true, offlineSkipConfirm: false },
  saves: { repairAfterQuit: { er: true, nr: true }, backupBeforeLaunch: false, keepCopies: 10, keepDays: 30 },
  appearance: { theme: 'dark', effects: 'full', density: 'comfortable' },
  updates: { channel: 'stable', checkOnStart: true, me3Notices: true },
  logs: { keepDays: 30 },
};

/** Start with one changed setting so "changed from default" has something to show. */
export const initialSettings: Settings = { ...structuredClone(defaultSettings), updates: { ...defaultSettings.updates, channel: 'beta' } };

/* ------------------------------------------------------------------ builds */

/** Merged game data per profile. Profiles not listed here have nothing that overlaps. */
export const builds: Record<string, BuildReport> = {
  'er-sc': {
    profileId: 'er-sc',
    state: 'stale',
    baseline: { game: 'Elden Ring 1.16.1', exceptions: [{ modId: 'clevers-moveset', base: 'unknown' }] },
    builtOn: 'yesterday, 23:10',
    durationSec: 41,
    changes: [
      { kind: 'game-updated', title: 'Elden Ring updated 1.16.0 → 1.16.1', detail: "The game's own files changed, so every merge starts from new originals." },
      { kind: 'reordered', title: "You moved Clever's Moveset Modpack below Detailed Item Descriptions", detail: 'Order decides who wins a clash.' },
      { kind: 'removed', title: "Grand Merchant's folder went missing", detail: 'Its 60 shop rows are left out until it is back.' },
    ],
    families: ['params', 'text', 'animations', 'behaviour', 'scripts'],
    cells: [
      { modId: 'seamless-coop', family: 'text', outcome: 'merged', count: 14 },
      { modId: 'seamless-coop', family: 'scripts', outcome: 'lost', count: 1 },
      { modId: 'detailed-item-descriptions', family: 'text', outcome: 'merged', count: 211 },
      { modId: 'detailed-item-descriptions', family: 'text', outcome: 'lost', count: 1 },
      { modId: 'clevers-moveset', family: 'params', outcome: 'merged', count: 38 },
      { modId: 'clevers-moveset', family: 'params', outcome: 'picked', count: 1 },
      { modId: 'clevers-moveset', family: 'params', outcome: 'lost', count: 2 },
      { modId: 'clevers-moveset', family: 'params', outcome: 'dropped', count: 1 },
      { modId: 'clevers-moveset', family: 'animations', outcome: 'merged', count: 37 },
      { modId: 'clevers-moveset', family: 'animations', outcome: 'picked', count: 1 },
      { modId: 'clevers-moveset', family: 'animations', outcome: 'lost', count: 2 },
      { modId: 'clevers-moveset', family: 'behaviour', outcome: 'unsupported', count: 1 },
      { modId: 'grand-merchant', family: 'params', outcome: 'dropped', count: 60 },
      { modId: 'convergence', family: 'params', outcome: 'merged', count: 1842 },
      { modId: 'convergence', family: 'params', outcome: 'won', count: 2 },
      { modId: 'convergence', family: 'text', outcome: 'merged', count: 3104 },
      { modId: 'convergence', family: 'text', outcome: 'won', count: 1 },
      { modId: 'convergence', family: 'animations', outcome: 'merged', count: 410 },
      { modId: 'convergence', family: 'animations', outcome: 'won', count: 2 },
      { modId: 'convergence', family: 'behaviour', outcome: 'unsupported', count: 1 },
      { modId: 'convergence', family: 'scripts', outcome: 'unknown', count: 1 },
    ],
    // Winners and reasons are computed by the mock from rules, picks and load order; builtWinnerId is the last build.
    clashes: [
      { id: 'c1', family: 'params', file: 'regulation.bin', piece: 'Dagger · attack power', sides: [{ modId: 'clevers-moveset', value: '110' }, { modId: 'convergence', value: '125' }], resolution: 'order', builtWinnerId: 'convergence' },
      { id: 'c2', family: 'params', file: 'regulation.bin', piece: 'Dagger · weight', sides: [{ modId: 'clevers-moveset', value: '1.5' }, { modId: 'convergence', value: '2.0' }], resolution: 'pick', pickedId: 'clevers-moveset', needsReview: true, builtWinnerId: 'clevers-moveset', rebase: { wasVanilla: '2.0', nowVanilla: '1.8', modId: 'clevers-moveset' } },
      { id: 'c3', family: 'params', file: 'regulation.bin', piece: 'New weapon 1100500 (both mods added one)', sides: [{ modId: 'clevers-moveset', value: "Clever's Rapier" }, { modId: 'convergence', value: 'Carian Needle' }], resolution: 'order', canKeepBoth: true, builtWinnerId: 'convergence' },
      { id: 'c4', family: 'animations', file: 'c0000.anibnd', piece: 'Dash', sides: [{ modId: 'clevers-moveset', value: 'shorter dash, 14 frames' }, { modId: 'convergence', value: 'dash with a step, 18 frames' }], resolution: 'order', builtWinnerId: 'convergence' },
      { id: 'c5', family: 'animations', file: 'c0000.anibnd', piece: 'Dagger light attack 1', sides: [{ modId: 'clevers-moveset', value: 'new chain, 3 hits' }, { modId: 'convergence', value: 'vanilla timing, new hitbox' }], resolution: 'order', builtWinnerId: 'clevers-moveset' },
      { id: 'c6', family: 'animations', file: 'c0000.anibnd', piece: 'Dagger heavy attack', sides: [{ modId: 'clevers-moveset', value: 'lunge' }, { modId: 'convergence', value: 'overhead' }], resolution: 'order', builtWinnerId: 'convergence' },
      { id: 'c7', family: 'text', file: 'menu.msgbnd · item descriptions', piece: 'Dagger description', sides: [{ modId: 'detailed-item-descriptions', value: '"A short blade. Scales with dexterity (C) and strength (D)."' }, { modId: 'convergence', value: '"A dagger reforged in Carian silver."' }], resolution: 'order', builtWinnerId: 'convergence' },
      { id: 'c8', family: 'behaviour', file: 'c0000.behbnd', piece: 'Player behaviour graphs (whole file)', sides: [{ modId: 'clevers-moveset', value: '41 new behaviours' }, { modId: 'convergence', value: '12 new behaviours' }], resolution: 'order', unsupported: true, builtWinnerId: 'convergence' },
      { id: 'c9', family: 'scripts', file: 'm00_00_00_00.talkesdbnd · grace menu', piece: 'Grace menu · "Summon friends" option', sides: [{ modId: 'seamless-coop', value: 'adds the option' }, { modId: 'convergence', value: 'removes the menu state it hangs off' }], resolution: 'order', conflict: 'delete-edit', unresolved: true, builtWinnerId: 'convergence' },
    ],
    rules: [
      { id: 'r1', family: 'animations', order: ['clevers-moveset', 'convergence'], coupled: ['behaviour'], meetsNew: 1, metIds: ['c6'] },
    ],
    pending: [],
    dropped: [
      { id: 'd1', modId: 'clevers-moveset', family: 'params', file: 'regulation.bin', what: 'its armour stats (EquipParamProtector)', reason: 'Made for game 1.12. Its rows are a different size now, so they cannot be read.', fix: 'The rest of the mod still applies. An update from its author fixes it.' },
      { id: 'd2', modId: 'grand-merchant', family: 'params', file: 'regulation.bin', what: '60 shop listings (ShopLineupParam)', reason: 'Its folder is missing.', fix: 'Install it again, or remove it from the profile.' },
    ],
    kept: [
      { family: 'params', count: 1880, unit: 'parameter rows' },
      { family: 'text', count: 3329, unit: 'text lines' },
      { family: 'animations', count: 447, unit: 'animations' },
    ],
    reportLines: [
      'Bayle 3.14.1 · Seamless + Convergence · built yesterday 23:10 in 41 s',
      'Originals: Elden Ring 1.16.0 (now 1.16.1: stale)',
      'Base: vanilla for every mod. Clever\'s Moveset Modpack does not say what it was made against; compared against vanilla anyway.',
      'regulation.bin: 1,880 rows merged from 3 mods · 2 clashes · 1 table skipped',
      '  EquipParamWeapon 1000: attack power, Clever\'s Moveset 110 vs Convergence 125, Convergence wins (order)',
      '  EquipParamWeapon 1000: weight, Clever\'s Moveset 1.5 vs Convergence 2.0, Clever\'s Moveset wins (your pick)',
      '  EquipParamWeapon 1100500: added by both, Convergence wins (order). Keep both not applied: needs your approval.',
      '  EquipParamProtector: skipped for Clever\'s Moveset, row size 1,004 expected 1,012',
      'menu.msgbnd: 3,329 lines merged from 3 mods · 1 clash',
      '  item descriptions 1000: Detailed Item Descriptions vs Convergence, Convergence wins (order)',
      'c0000.anibnd: 447 animations merged from 2 mods · 3 clashes',
      'c0000.behbnd: not a mergeable type. Convergence\'s file used whole. Compatibility unknown.',
      'c0000.hks: Convergence\'s copy used (no other mod ships it). Compiles; not tested in game.',
      'Textures: 128 files from Convergence, none shared',
      'Grand Merchant: folder missing, left out entirely',
    ],
  },
  'er-rev': {
    profileId: 'er-rev',
    state: 'ready',
    baseline: { game: 'Elden Ring 1.16.1', exceptions: [] },
    builtOn: 'today, 00:31',
    durationSec: 28,
    changes: [],
    families: ['text'],
    cells: [
      { modId: 'seamless-coop', family: 'text', outcome: 'merged', count: 14 },
      { modId: 'revive', family: 'text', outcome: 'merged', count: 96 },
    ],
    clashes: [],
    rules: [],
    pending: [],
    dropped: [],
    kept: [{ family: 'params', count: 322, unit: 'parameter rows' }, { family: 'text', count: 110, unit: 'text lines' }],
    reportLines: ['Bayle 3.14.1 · Revive co-op · built today 00:31 in 28 s', 'regulation.bin: 322 rows from Nightreign Revive, no clashes', 'menu.msgbnd: 110 lines merged from 2 mods, no clashes', 'c0000.hks: Revive\'s hook appended. Compiles; not tested in game.'],
  },
};

/** Pieces only one mod touches, so "why is my game doing X" has more to find than clashes. */
export const soloPieces: PieceHit[] = [
  { family: 'params', file: 'regulation.bin', piece: 'EquipParamWeapon · 1000 Dagger · stamina cost', changedBy: ['clevers-moveset'], value: '21', winnerId: 'clevers-moveset' },
  { family: 'params', file: 'regulation.bin', piece: 'CharaInitParam · 3000 Wretch · vigor', changedBy: ['convergence'], value: '12', winnerId: 'convergence' },
  { family: 'text', file: 'menu.msgbnd · item names', piece: 'Item 1000 · Dagger', changedBy: ['convergence'], value: '"Carian Dagger"', winnerId: 'convergence' },
  { family: 'text', file: 'menu.msgbnd · menu text', piece: 'Line 5001 · grace menu', changedBy: ['seamless-coop'], value: '"Summon friends"', winnerId: 'seamless-coop' },
  { family: 'animations', file: 'c0000.anibnd', piece: 'a000_002000 · roll', changedBy: ['clevers-moveset'], value: 'quickstep, 13 frames', winnerId: 'clevers-moveset' },
  { family: 'animations', file: 'c0000.anibnd', piece: 'a000_005000 · backstep', changedBy: ['convergence'], value: 'longer backstep, 20 frames', winnerId: 'convergence' },
  { family: 'params', file: 'regulation.bin', piece: 'SpEffectParam · 100 Rot of Pride · hp per second', changedBy: ['convergence'], value: '-4', winnerId: 'convergence' },
  { family: 'params', file: 'regulation.bin', piece: 'ShopLineupParam · 100000 Kalé · Dagger', changedBy: ['grand-merchant'], value: 'price 800', winnerId: 'grand-merchant' },
];
