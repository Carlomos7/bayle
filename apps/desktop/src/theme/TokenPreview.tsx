import tokensCss from "./tokens.css?raw";
import { AppearanceControls } from "./AppearanceControls";

// Colour roles = the custom properties of the first (dark) block; the other themes define the same names.
const first = tokensCss.slice(tokensCss.indexOf("{"), tokensCss.indexOf("}"));
const COLOURS = [...first.matchAll(/--([a-z-]+):/g)].map((m) => m[1]!);
const SIZES = ["caption", "body", "row", "section", "page"] as const;
const SPACES = [2, 4, 6, 8, 10, 12, 16, 20, 24, 32, 40];
const RADII = ["tag", "card", "control", "launch", "overlay", "inset", "pill"] as const;

/** Dev-only page (route /dev/tokens): every colour role, the type scale, spacing and radii under the live theme. */
export function TokenPreview() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-page font-semibold text-title">Theme tokens</h1>
      <AppearanceControls />
      <section aria-label="Colours" className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-2">
        {COLOURS.map((name) => (
          <div key={name} className="flex items-center gap-2 text-caption">
            <span
              className="size-6 shrink-0 rounded-tag border border-border-edge"
              style={{ background: `var(--${name})` }}
            />
            {name}
          </div>
        ))}
      </section>
      <section aria-label="Type" className="flex flex-col gap-1">
        {SIZES.map((s) => (
          <p key={s} style={{ fontSize: `var(--text-${s})` }}>
            {s} ({`var(--text-${s})`}) The Lands Between
          </p>
        ))}
      </section>
      <section aria-label="Spacing" className="flex flex-col gap-1">
        {SPACES.map((px) => (
          <div key={px} className="flex items-center gap-2 text-caption">
            <span className="h-2 rounded-tag bg-accent" style={{ width: px }} />
            sp{px}
          </div>
        ))}
      </section>
      <section aria-label="Radius" className="flex gap-3">
        {RADII.map((r) => (
          <div
            key={r}
            className="grid h-12 w-16 place-items-center border border-gold-line bg-surface-card text-caption"
            style={{ borderRadius: `var(--radius-${r})` }}
          >
            {r}
          </div>
        ))}
      </section>
    </div>
  );
}
