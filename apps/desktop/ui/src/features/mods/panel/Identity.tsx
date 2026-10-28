import type { Mod } from '@/api';
import { Button, LinkButton } from '@/components/ui/button';
import { useMods } from '../controller';
import { dllFile, dllsOf, nameSourceText, namedByFile, ownerOf } from '../identity';
import { Group, Row } from './parts';

/* ------------------------------------------------------------------ identity */

/**
 * What a mod is called, where that name came from, and what it is made of.
 * For a DLL: its name, its file, the mod it belongs to, and what the file says
 * about itself. For a package: the DLLs it came with.
 */
export function Identity({ mod: m }: { mod: Mod }) {
  const c = useMods();
  const owner = ownerOf(m, c.profile);
  if (m.kind === 'package') {
    const dlls = dllsOf(m, c.profile);
    if (!dlls.length) return null;
    return (
      <Group title="Comes with">
        {dlls.map((d) => (
          <Row key={d.id} label={dllFile(d)!} help="Its DLL, listed under Natives. me3 loads it separately, in its own order.">
            <LinkButton className="text-xs" onClick={() => c.openPanel(d.id)}>Open</LinkButton>
          </Row>
        ))}
      </Group>
    );
  }
  const details = m.fileDetails && (m.fileDetails.product || m.fileDetails.description);
  return (
    <Group title="This DLL">
      {namedByFile(m) ? (
        <Row label="No name found" help="Its file has no product name, it did not come with a named mod, and Bayle does not recognize it. Naming it makes it easier to spot.">
          <Button size="sm" onClick={() => c.askRename(m.id)}>Name it</Button>
        </Row>
      ) : (
        <Row label={m.name} help={nameSourceText(m, c.profile)}>
          <Button size="sm" variant="ghost" onClick={() => c.askRename(m.id)}>Rename</Button>
        </Row>
      )}
      <Row label="File" help="What me3 loads. Crash logs and mod pages usually name this file.">
        <code className="text-code">{dllFile(m)}</code>
      </Row>
      {owner && (
        <Row label="Part of" help="It came in the same download. Turning one off does not turn off the other.">
          <LinkButton className="text-ui" onClick={() => c.openPanel(owner.id)}>{owner.name}</LinkButton>
        </Row>
      )}
      <Row label="File details" help={details ? 'What the DLL says about itself. Authors fill this in, or don\'t.' : 'The DLL says nothing about itself.'}>
        {details ? <span className="text-right text-ui">{m.fileDetails!.product}{m.fileDetails!.description ? <span className="block text-xs text-t3">{m.fileDetails!.description}</span> : null}</span> : <span className="text-xs text-t4">none</span>}
      </Row>
    </Group>
  );
}
