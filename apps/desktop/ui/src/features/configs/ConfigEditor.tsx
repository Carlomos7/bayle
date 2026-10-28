import { useState } from 'react';
import { ChevronRight, ExternalLink, FolderOpen, MoreHorizontal, Unlink } from 'lucide-react';
import type { ConfigFile } from '@/api';
import { useAction, useCall } from '@/data/hooks';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/bayle/controls';
import { DropdownMenu, item, sep } from '@/components/bayle/menu';
import { SectionLabel } from '@/components/bayle/layout';
import { plural } from '@/lib/utils';
import { FieldRow } from './FieldRow';
import { MarkdownView, TextEditor } from './TextEditor';
import { isMarkdown, isTextOnly, type ConfigDraft } from './useConfigDraft';

export interface ConfigEditorProps {
  profileId: string;
  file: ConfigFile;
  draft: ConfigDraft;
  onSave: () => void;
  saving: boolean;
}

/** Right column: one settings file as a form, or as text. */
export function ConfigEditor({ profileId, file, draft, onSave, saving }: ConfigEditorProps) {
  const call = useCall();
  const { run } = useAction();
  const textOnly = isTextOnly(file);
  const [asText, setAsText] = useState(false);
  const [mdEdit, setMdEdit] = useState(false);
  const showText = textOnly || asText;
  const formDirty = draft.count > (draft.textEdited ? 1 : 0);
  const folder = file.path.replace(/[\\/][^\\/]*$/, '');

  const toggleText = (on: boolean) => setAsText(on);
  const lockReason = formDirty ? 'Save or discard the form changes first' : draft.textEdited ? 'Save or discard the text changes first' : undefined;

  return (
    <div className="flex min-w-0 flex-col">
      <div className="flex flex-wrap items-start gap-3 border-b border-line pb-3">
        <div className="min-w-0 flex-1 basis-[260px]">
          <div className="flex flex-wrap items-center gap-x-1.5 text-body">
            <b className="font-semibold">{file.modName}</b>{file.viaFile && <><ChevronRight className="size-3 text-t4" /><span className="font-mono text-t3">{file.viaFile}</span></>}<ChevronRight className="size-3 text-t4" /><span className="font-mono text-t2">{file.name}</span>
          </div>
          <div className="mt-0.5 truncate font-mono text-xs text-t4" title={file.path}>{file.path}</div>
        </div>
        {!textOnly && (
          <label className="flex items-center gap-2 text-xs text-t2" title={lockReason}>
            Edit as text
            <Switch checked={asText} onCheckedChange={toggleText} disabled={!!lockReason} aria-label="Edit as text" />
          </label>
        )}
        {isMarkdown(file) && <Button size="sm" variant="ghost" onClick={() => setMdEdit(!mdEdit)} aria-pressed={mdEdit}>{mdEdit ? 'Read' : 'Edit'}</Button>}
        <DropdownMenu align="end" items={[
          item('Open in editor', () => void call((a) => a.openPath(file.path)), { icon: <ExternalLink /> }),
          item('Open folder', () => void call((a) => a.openPath(folder)), { icon: <FolderOpen /> }),
          sep,
          item('Detach from this mod', () => void run((a) => a.detachConfig(profileId, file.modId, file.name)), { icon: <Unlink />, hint: 'The file stays where it is' }),
        ]} trigger={<Button variant="ghost" size="sm" iconOnly aria-label="More for this file" icon={<MoreHorizontal />} />} />
      </div>

      <div className="pt-4">
        {isMarkdown(file) && !mdEdit ? <MarkdownView text={draft.text} />
          : showText ? (
            <div className="flex flex-col gap-2">
              {textOnly && !isMarkdown(file) && <p className="m-0 text-xs text-t3">Bayle can't show this file as settings, so it is open here to edit directly.</p>}
              <TextEditor value={draft.text} onChange={draft.setText} label={`${file.name} as text`} />
            </div>
          ) : (
            <div className="flex flex-col gap-5">
              {file.sections?.map((s) => (
                <section key={s.name} aria-label={s.name}>
                  <SectionLabel className="font-mono tracking-normal text-t2">[{s.name}]</SectionLabel>
                  {s.note && <p className="m-0 mt-1 text-xs text-t3">{s.note}</p>}
                  <div className="mt-1">
                    {s.fields.map((f) => (
                      <FieldRow key={f.key} section={s.name} field={f} value={draft.value(s.name, f)} edited={draft.isEdited(s.name, f)} error={draft.error(s.name, f)}
                        onChange={(v) => draft.setValue(s.name, f.key, v)} />
                    ))}
                  </div>
                </section>
              ))}
            </div>
          )}
      </div>

      {draft.count > 0 && (
        <div role="region" aria-label="Unsaved changes" data-unsaved-bar className="sticky bottom-0 z-[2] mt-5 -mb-2 flex items-center gap-3 rounded-lg border border-line2 bg-raise px-4 py-2.5 shadow-pop animate-[rise_.14s_ease-out]">
          <span className="size-1.5 rounded-full bg-accent" />
          <span className="flex-1 text-ui"><b className="font-semibold">{plural(draft.count, 'unsaved change')}</b><span className="ml-1.5 text-t3">Nothing is written until you save.</span></span>
          <Button variant="ghost" size="sm" onClick={draft.discard}>Discard</Button>
          <Button variant="primary" size="sm" onClick={onSave} disabled={saving || !draft.valid} title={draft.valid ? undefined : 'Fix the highlighted values first'}>Save <span className="font-mono text-micro opacity-70">Ctrl S</span></Button>
        </div>
      )}
    </div>
  );
}
