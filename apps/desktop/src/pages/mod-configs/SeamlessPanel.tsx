import { Clipboard, Copy, FolderOpen, Save } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Card, Choice, FormRow, Spin, TextField } from "./controls";
import type { SeamlessView } from "./types";

export interface SeamlessModel {
  view: Partial<SeamlessView>;
  /** The waiting edit of a Seamless setting, or its value on disk. */
  get(section: string, key: string, disk: string): string;
  set(section: string, key: string, value: string): void;
  setPreset(name: string): void;
  words: Record<string, string>;
  copy(): void;
  paste(): void;
  /** The text of a settings file the player loaded. */
  load(text: string): void;
  saveAs(): void;
}

/**
 * Seamless Co-op's own panel: the password with its hint, difficulty (party-size presets and the per-player numbers),
 * the language, the other settings (`children`), and sharing with a friend. Edits wait on the page until Save.
 */
export function SeamlessPanel({ model, children }: { model: SeamlessModel; children: ReactNode }) {
  const { view: s, words } = model;
  const [shown, setShown] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const scaling = (s.scaling ?? []).map((x) => ({ ...x, now: Number.parseInt(model.get("SCALING", x.key, String(x.value)), 10) || 0 }));
  const preset = scaling.length
    ? (Object.entries(s.presetValues ?? {}).find(([, v]) => v.length === scaling.length && v.every((n, i) => n === scaling[i]?.now))?.[0] ?? "Custom")
    : (s.preset ?? "");
  const presetChoices = (s.presetKeys ?? []).map((k, i) => ({ value: k, label: (s.presets ?? [])[i] ?? k }));
  const language = model.get("LANGUAGE", "mod_language_override", s.language ?? "");

  return (
    <div className="flex flex-col gap-4">
      {s.hasPassword ? (
        <Card>
          <FormRow title={words.password ?? ""} help={words.passwordHint} divider={false} testId="seamlessPassword">
            {(id) => (
              <>
                <TextField id={id} type={shown ? "text" : "password"} value={model.get("PASSWORD", "cooppassword", s.password ?? "")} onChange={(v) => model.set("PASSWORD", "cooppassword", v)} />
                <Button className="h-7 min-w-0 px-2 text-caption" aria-pressed={shown} onClick={() => setShown((x) => !x)}>
                  {shown ? words.hidePassword : words.showPassword}
                </Button>
              </>
            )}
          </FormRow>
        </Card>
      ) : null}
      {scaling.length > 0 ? (
        <section className="flex flex-col gap-2" aria-label={words.difficulty}>
          <h3 className="font-semibold text-body">{words.difficulty}</h3>
          <Card>
            <FormRow title={words.preset ?? ""} help={s.scalingHint}>
              {(id) => <Choice id={id} value={preset} choices={presetChoices} onChange={model.setPreset} />}
            </FormRow>
            {scaling.map((x, i) => (
              <FormRow key={x.key} title={x.label} divider={i < scaling.length - 1}>
                {(id) => <Spin id={id} value={x.now} lo={0} hi={1000} onChange={(n) => model.set("SCALING", x.key, String(n))} />}
              </FormRow>
            ))}
          </Card>
        </section>
      ) : null}
      <Card>
        <FormRow title={words.language ?? ""} divider={false}>
          {(id) => <Choice id={id} value={language} choices={s.languages ?? []} onChange={(v) => model.set("LANGUAGE", "mod_language_override", v)} />}
        </FormRow>
      </Card>
      {children}
      <section className="flex flex-col gap-2" aria-label={words.share}>
        <h3 className="font-semibold text-body">{words.share}</h3>
        <Card className="flex flex-col gap-2 p-4">
          <p className="text-caption text-text-secondary">{words.shareBody}</p>
          <div className="flex flex-wrap gap-2">
            <Button onClick={model.copy}>
              <Copy aria-hidden className="size-4" />
              {words.copy}
            </Button>
            <Button onClick={model.paste}>
              <Clipboard aria-hidden className="size-4" />
              {words.paste}
            </Button>
            <Button onClick={() => file.current?.click()}>
              <FolderOpen aria-hidden className="size-4" />
              {words.load}
            </Button>
            <Button onClick={model.saveAs}>
              <Save aria-hidden className="size-4" />
              {words.saveAs}
            </Button>
            <input
              ref={file}
              type="file"
              accept=".ini,.txt,.json"
              className="hidden"
              aria-label={words.load}
              tabIndex={-1}
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) void f.text().then(model.load);
              }}
            />
          </div>
          {s.fingerprint ? (
            <p className="whitespace-pre-line text-caption text-text-secondary">
              {s.fingerprint}
              {s.fingerprintNote ? `\n${s.fingerprintNote}` : ""}
            </p>
          ) : null}
        </Card>
      </section>
    </div>
  );
}
