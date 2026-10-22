import { Button } from "@/components/ui/button";
import { Modal } from "./Dialog";

export interface Me3Facts {
  path?: string;
  version?: string;
  info?: Record<string, string>;
  latest?: { version?: string } | null;
  update?: boolean;
}

/** What `shell.me3` learned: where me3 is, its version, its folders and the newest release. */
export function Me3Dialog({ facts, onClose }: { facts: Me3Facts | null; onClose(): void }) {
  if (!facts) return null;
  const rows: [string, string | undefined][] = [
    ["Program", facts.path],
    ["Version", facts.version],
    ["Latest release", facts.latest?.version ? `${facts.latest.version}${facts.update ? " (newer)" : ""}` : undefined],
    ["Profiles folder", facts.info?.profile_dir],
    ["Logs folder", facts.info?.logs_dir],
    ["Install prefix", facts.info?.install_prefix],
  ];
  return (
    <Modal
      open
      onClose={onClose}
      title="The mod loader (me3)"
      footer={
        <Button variant="primary" onClick={onClose}>
          Close
        </Button>
      }
    >
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-body">
        {rows
          .filter(([, v]) => v)
          .map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-text-secondary">{k}</dt>
              <dd className="min-w-0 break-all">{v}</dd>
            </div>
          ))}
      </dl>
    </Modal>
  );
}
