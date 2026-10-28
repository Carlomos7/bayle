import { describe, expect, it } from 'vitest';
import { fieldKey, parseForm, valueText } from './configForm';

const INI = `; Seamless
[GAMEPLAY]
; Friends type this to join.
cooppassword = hunter2
; 0 = false, 1 = true. default: 1
allow_summons = 1
; 0 = Normal | 1 = None | 2 = Heavy
mode = 2
; 0 = MUTE, 10 = MAX
volume = 7
name = free text
name = twice
unknown line without equals
`;

describe('INI form', () => {
  const f = parseForm('ini', INI)!;
  const fields = f.sections[0]!.fields;
  const by = (k: string) => fields.find((x) => x.key === k)!;

  it('reads kinds, help and defaults from the comment above each setting', () => {
    expect(f.sections.map((s) => s.name)).toEqual(['GAMEPLAY']);
    expect(by('cooppassword')).toMatchObject({ type: 'secret', value: 'hunter2', help: 'Friends type this to join.' });
    expect(by('allow_summons')).toMatchObject({ type: 'bool', value: true, default: true });
    expect(by('mode')).toMatchObject({ type: 'enum', value: '2', options: [{ value: '0', label: 'Normal' }, { value: '1', label: 'None' }, { value: '2', label: 'Heavy' }] });
    expect(by('volume')).toMatchObject({ type: 'int', value: 7 });
  });

  it('shows a key written twice read-only, and skips lines that are not settings', () => {
    expect(fields.filter((x) => x.key === 'name').map((x) => x.type)).toEqual(['readonly', 'readonly']);
    expect(fields).toHaveLength(6);
  });

  it('remembers where each field sits, even when section names hold dots', () => {
    expect(f.spots.get(fieldKey('GAMEPLAY', 'mode'))).toMatchObject({ section: 'GAMEPLAY', key: 'mode' });
    expect(parseForm('ini', '[a.b]\nx = 1\n')!.spots.get('a.b.x')).toMatchObject({ section: 'a.b', key: 'x' });
  });

  it('keeps settings before the first section under an empty name; no settings gives no form', () => {
    expect(parseForm('ini', 'x = 1\n')!.sections[0]!.name).toBe('');
    expect(parseForm('ini', '; only a comment\n')).toBeNull();
  });

  it('words a switch the way the file spells it', () => {
    const spot = (raw: string) => ({ section: '', key: 'k', type: 'bool' as const, raw });
    expect(valueText(spot('1'), false)).toBe('0');
    expect(valueText(spot('True'), false)).toBe('False');
    expect(valueText(spot('ON'), false)).toBe('OFF');
    expect(valueText(spot('yes'), false)).toBe('no');
    expect(valueText(spot('0'), true)).toBe('1');
    expect(valueText({ ...spot('1'), type: 'int' }, 5)).toBe('5');
  });
});

const TOML = `# top
title = "Mod" # trailing
[server]
# how many
port = 8080
ratio = 1.5
on = true
list = [1, 2]
long = """
a = 1
"""
inline = { a = 1 }

[[builds]]
name = 'one'
[[builds]]
name = 'two'
`;

describe('TOML form', () => {
  const f = parseForm('toml', TOML)!;
  it('reads tables, arrays of tables and one-line scalars; the rest is read-only or left to text', () => {
    expect(f.sections.map((s) => s.name)).toEqual(['', 'server', '[[builds]] #1', '[[builds]] #2']);
    const server = f.sections[1]!.fields;
    expect(server.map((x) => [x.key, x.type, x.value])).toEqual([['port', 'int', 8080], ['ratio', 'float', 1.5], ['on', 'bool', true], ['list', 'readonly', '[1, 2]'], ['long', 'readonly', '"""']]);
    expect(server[0]!.help).toBe('how many');
    expect(f.sections[0]!.fields[0]).toMatchObject({ key: 'title', value: 'Mod' });
    expect(f.sections[3]!.fields[0]).toMatchObject({ value: 'two' });
  });
  it('gives no form for text that has no settings', () => {
    expect(parseForm('toml', '# nothing\n')).toBeNull();
  });
});
