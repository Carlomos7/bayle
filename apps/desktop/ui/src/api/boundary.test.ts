/**
 * The security boundary, checked on the source and the built app:
 * React reaches the engine only through the Rust gateway. No ports, tokens,
 * engine URLs or direct HTTP outside the mock; only gateway/tauri.ts imports
 * Tauri; pages and components never import a transport; and a production
 * build carries no mock data.
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { beforeAll, describe, expect, it } from 'vitest';

const ROOT = join(__dirname, '..', '..');
const SRC = join(ROOT, 'src');
const files = (dir: string): string[] => readdirSync(dir).flatMap((f) => { const p = join(dir, f); return statSync(p).isDirectory() ? files(p) : /\.(ts|tsx)$/.test(f) ? [p] : []; });
const rel = (p: string) => relative(SRC, p).split(sep).join('/');
const isTest = (p: string) => /\.test(-util)?\.(ts|tsx)$/.test(p);
/** The development stand-ins: allowed to fake the engine, never loaded in the desktop app. */
const isMock = (r: string) => r.startsWith('api/mock/') || r === 'api/gateway/mock.ts' || r === 'api/preview.ts';
const app = files(SRC).filter((p) => !isTest(p) && rel(p) !== 'routeTree.gen.ts');
const prod = app.filter((p) => !isMock(rel(p)));

/** Source without comments: docs may name engine paths; code may not. */
const code = (p: string) => readFileSync(p, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`])\/\/.*$/gm, '$1');
const offenders = (list: string[], re: RegExp) => list.filter((p) => re.test(code(p))).map(rel);

describe('security boundary (source)', () => {
  it('has no engine address, port, token or auth header in the app', () => {
    expect(offenders(prod, /127\.0\.0\.1|localhost:\d|\bBearer\b|BAYLE_API_TOKEN|Authorization|\/v1\//)).toEqual([]);
  });

  it('makes no direct HTTP or SSE requests (Rust owns the engine connection)', () => {
    expect(offenders(prod, /\bfetch\s*\(|new EventSource|XMLHttpRequest|new WebSocket/)).toEqual([]);
  });

  it('imports Tauri in exactly one file, the transport', () => {
    expect(offenders(app, /from ['"]@tauri-apps\//)).toEqual(['api/gateway/tauri.ts']);
  });

  it('uses no broad Tauri plugins (fs, shell, http, process) from the frontend', () => {
    expect(offenders(app, /@tauri-apps\/plugin-(fs|shell|http|process)/)).toEqual([]);
  });

  it('keeps transports out of pages and components: they use hooks', () => {
    const ui = app.filter((p) => /^(features|components|app|routes)\//.test(rel(p)));
    expect(offenders(ui, /api\/gateway\/(tauri|mock|transport)|api\/mock\//)).toEqual([]);
  });

  it('never selects the mock without the dev or demo flag', () => {
    const index = readFileSync(join(SRC, 'api', 'index.ts'), 'utf8');
    expect(index).toMatch(/if \(o\.inTauri\) return 'desktop';/);
    expect(index).toMatch(/import\('@\/api\/preview'\)/); // swapped for a stub in desktop builds (vite.config.ts)
    expect(index).not.toMatch(/^import (?!type )[^;]*from '\.\/(mock|gateway\/mock)/m); // type-only imports vanish at build
  });
});

const DIST = join(ROOT, 'dist');
const built = existsSync(join(DIST, 'index.html'));

describe.skipIf(!built)('security boundary (production build in dist/)', () => {
  let all = '';
  beforeAll(() => { all = readdirSync(join(DIST, 'assets')).filter((f) => f.endsWith('.js')).map((f) => readFileSync(join(DIST, 'assets', f), 'utf8')).join('\n'); });

  it('carries no mock data', () => {
    expect(all).not.toContain("Clever's Moveset Modpack");
    expect(all).not.toContain('createMockEngine');
  });

  it('carries no engine address or token handling', () => {
    expect(all).not.toMatch(/127\.0\.0\.1|BAYLE_API_TOKEN|Bearer /);
  });

  it('loads nothing from a CDN: scripts, styles and fonts are local', () => {
    const html = readFileSync(join(DIST, 'index.html'), 'utf8');
    expect(html).not.toMatch(/(src|href)="https?:\/\//);
    const css = readdirSync(join(DIST, 'assets')).filter((f) => f.endsWith('.css')).map((f) => readFileSync(join(DIST, 'assets', f), 'utf8')).join('\n');
    expect(css).not.toMatch(/url\(\s*["']?https?:/);
  });
});
