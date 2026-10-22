import { Card, Segmented } from "./ui";
import { W } from "./words";

/** A mod that differs from an installed one (profile_import clashes), as the presenter words it. */
export interface Clash {
  key: string;
  name: string;
  diff: string;
  incoming: string;
  mine: string;
  choice: string;
  suggested: boolean;
  canBoth: boolean;
}

type Pick = "incoming" | "mine" | "both";

export function Clashes({ clashes, disabled, onPick }: { clashes: Clash[]; disabled: boolean; onPick: (key: string, c: Pick) => void }) {
  if (!clashes.length) return null;
  return (
    <section className="flex flex-col gap-2" aria-label={W.differsTitle}>
      <h3 className="font-semibold text-body text-title">{W.differsTitle}</h3>
      <p className="text-text-secondary">{W.differsAbout}</p>
      {clashes.map((c) => (
        <Card key={c.key}>
          <h4 className="font-semibold text-title">{c.name}</h4>
          <p className="text-caption text-text-secondary">{c.diff}</p>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="font-semibold">{W.incomingCopy}</p>
              <p>{c.incoming}</p>
            </div>
            <div>
              <p className="font-semibold">{W.yourCopy}</p>
              <p>{c.mine}</p>
            </div>
          </div>
          <Segmented<Pick>
            label={`${c.name}: copy to use`}
            value={(c.choice as Pick) || ""}
            disabled={disabled}
            options={[
              { value: "incoming", label: W.useIncoming },
              { value: "mine", label: W.keepMine },
              ...(c.canBoth ? [{ value: "both" as const, label: W.keepBoth }] : []),
            ]}
            onChange={(v) => onPick(c.key, v)}
          />
          <p className="text-caption text-text-secondary">
            {c.choice === "" ? W.pickOne : c.suggested && c.choice === "incoming" ? W.suggested : ""}
          </p>
        </Card>
      ))}
    </section>
  );
}
