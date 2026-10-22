import { ConfigForm, type FormModel } from "./ConfigForm";
import type { OverhaulView } from "./types";

/** The Overhaul setup: the basic level is generated rows (per DLL, the Files table, texts, the log check); an advanced or verified setup shows what it does, read-only. */
export function OverhaulSetup({ view, model }: { view: OverhaulView; model: FormModel }) {
  return (
    <div className="flex flex-col gap-4">
      <h2 className="font-semibold text-row">
        {view.label} · {view.status}
      </h2>
      {view.loadsLast && view.sections.length > 0 ? <p className="text-caption text-text-secondary">{view.loadsLast}</p> : null}
      {view.note ? (
        <p data-testid="overhaulNote" className="text-caption text-text-secondary">
          {view.note}
        </p>
      ) : null}
      <ConfigForm model={{ ...model, sections: view.sections }} />
      {view.steps.length > 0 ? (
        <section className="flex flex-col gap-1">
          <h3 className="font-semibold text-body">{view.stepsTitle}</h3>
          <ul className="flex flex-col gap-1 text-body">
            {view.steps.map((s, i) => (
              <li key={`${i}-${s}`}>{s}</li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
