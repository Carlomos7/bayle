import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Download, FolderOpen, MoreHorizontal, Pencil, Settings } from "lucide-react";
import { Switch } from "radix-ui";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { useMods } from "./context";
import { useModsHost } from "./install-contract";
import { inputClass, Menu, MenuCheck, MenuItem, MenuSep, Pill } from "./ui";

/** The header strip: profile name (click to rename) · counts · merge health · Edit as text · Install mod · folder · gear · more. */
export function ModsHeader({
  editText,
  onEditText,
  onHealth,
  openSettings,
  openVersions,
  openLibrary,
}: {
  editText: boolean;
  onEditText(on: boolean): void;
  onHealth(): void;
  openSettings(): void;
  openVersions(): void;
  openLibrary(): void;
}) {
  const { view, words, actions, openAddExisting } = useMods();
  const host = useModsHost();
  const navigate = useNavigate();
  const [renaming, setRenaming] = useState(false);
  const [blocked, setBlocked] = useState("");
  const beginRename = () => {
    if (view.rename_block) {
      // a refusal to start (a job is running, the game is): said for a moment
      setBlocked(view.rename_block);
      setTimeout(() => setBlocked(""), 4000);
    } else setRenaming(true);
  };
  const overhaul = view.overhaul;
  const health = view.state.health;
  const staysLast = view.load_order.stays_last;
  return (
    <header className="flex flex-wrap items-center gap-2">
      <ProfileName editing={renaming} setEditing={setRenaming} note={blocked} begin={beginRename} />
      <span className="hidden text-caption text-text-tertiary min-[980px]:inline">·  {view.state.counts}</span>
      {health?.text ? <Pill level={health.level || "muted"} icon={health.level === "success" ? "Accept" : "Info"} text={health.text} tip={words.healthTip} onClick={onHealth} /> : null}
      <div className="ml-auto flex items-center gap-2">
        <label className="flex items-center gap-2 text-caption max-[760px]:hidden">
          {words.editAsText}
          <Switch.Root
            checked={editText}
            onCheckedChange={onEditText}
            className="relative h-5 w-9 rounded-pill border border-border-edge bg-surface-input data-[state=checked]:border-gold-line data-[state=checked]:bg-gold-fill-top"
          >
            <Switch.Thumb className="block size-3.5 translate-x-0.5 rounded-pill bg-text-primary transition-transform duration-toggle data-[state=checked]:translate-x-[18px] data-[state=checked]:bg-gold-text" />
          </Switch.Root>
        </label>
        <Menu
          label={words.install ?? ""}
          trigger={
            <Button variant="primary">
              <Download aria-hidden className="size-4" />
              {words.install}
            </Button>
          }
        >
          <MenuItem onSelect={() => host.openInstall({ from: "file" })}>{words.installFile}</MenuItem>
          <MenuItem onSelect={() => host.openInstall({ from: "folder" })}>{words.installFolder}</MenuItem>
        </Menu>
        <Button
          aria-label={words.profileFolder}
          title={words.profileFolder}
          onClick={actions.openProfileFolder}
        >
          <FolderOpen aria-hidden className="size-4" />
          <span className="max-[1060px]:sr-only">{words.profileFolder}</span>
        </Button>
        <Menu
          label={words.gearTip ?? ""}
          trigger={
            <Button aria-label={words.gearTip} title={words.gearTip} className="min-w-0 px-2.5">
              <Settings aria-hidden className="size-4" />
            </Button>
          }
        >
          <MenuItem onSelect={openSettings}>{words.profileSettings}</MenuItem>
          <MenuItem onSelect={openVersions}>{words.versions}</MenuItem>
          <MenuItem onSelect={() => void navigate({ to: "/profile-transfer" })}>{words.exportProfile}</MenuItem>
          <MenuItem onSelect={() => void navigate({ to: "/profile-transfer" })}>{words.importProfile}</MenuItem>
          <MenuSep />
          <MenuItem onSelect={beginRename}>{words.profileRenameTip}...</MenuItem>
          <MenuItem onSelect={actions.duplicate}>{words.duplicate}</MenuItem>
          {view.outside ? <MenuItem onSelect={actions.moveIn}>{words.moveIn}</MenuItem> : null}
          {staysLast?.can_fix ? <MenuItem onSelect={actions.fixOrder}>{words.fixLoadOrder}</MenuItem> : null}
          <MenuSep />
          <MenuItem onSelect={actions.deleteProfile}>{words.deleteProfile}</MenuItem>
        </Menu>
        <Menu
          label={words.more ?? ""}
          trigger={
            <Button aria-label={words.more} title={words.more} className="min-w-0 px-2.5">
              <MoreHorizontal aria-hidden className="size-4" />
            </Button>
          }
        >
          <MenuCheck checked={editText} onSelect={() => onEditText(!editText)}>
            {words.editAsText}
          </MenuCheck>
          <MenuItem onSelect={actions.refresh} shortcut="F5">
            {words.rescan}
          </MenuItem>
          <MenuItem onSelect={() => openAddExisting("package")}>{words.addExisting}</MenuItem>
          <MenuItem onSelect={openLibrary}>{words.library}</MenuItem>
          {overhaul.visible ? (
            <>
              <MenuSep />
              <MenuItem onSelect={actions.installOverhaul}>{overhaul.install}</MenuItem>
              <MenuItem disabled={!overhaul.can_remove} onSelect={actions.removeOverhaul}>
                {overhaul.remove}
              </MenuItem>
              <MenuItem disabled={!overhaul.can_take_over} onSelect={actions.takeOver}>
                {overhaul.take_over}
              </MenuItem>
              <MenuItem disabled={!overhaul.can_clean} onSelect={actions.cleanLeftovers}>
                {overhaul.clean}
              </MenuItem>
            </>
          ) : null}
        </Menu>
      </div>
    </header>
  );
}

/** The profile's name stands out on the page; click it (or the pencil, or Profile > Rename) to rename it, live-checked. */
function ProfileName({ editing, setEditing, note, begin }: { editing: boolean; setEditing(on: boolean): void; note: string; begin(): void }) {
  const { view, words, actions } = useMods();
  const title = view.state.title;
  const [text, setText] = useState(title);
  const [debounced, setDebounced] = useState(title);
  const [refused, setRefused] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const check = useQuery({
    queryKey: ["page", "mods", "name-check", view.profile, debounced],
    queryFn: () => actions.profileNameCheck(debounced),
    enabled: editing && debounced !== title && debounced !== "",
  });
  const problem = refused || (text === title || debounced !== text ? "" : (check.data ?? ""));
  useEffect(() => {
    if (editing) {
      input.current?.focus();
      input.current?.select();
    }
  }, [editing]);
  const change = (value: string) => {
    setText(value);
    setRefused("");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setDebounced(value), 250); // the live name check, once typing pauses
  };
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const cancel = () => {
    setEditing(false);
    setRefused("");
  };
  const apply = async () => {
    if (text === title) return cancel();
    const why = await actions.renameProfile(text);
    if (why) setRefused(why);
    else cancel();
  };

  if (!editing) {
    return (
      <div className="flex items-center gap-2">
        <button
          type="button"
          title={words.profileRenameTip}
          onClick={() => {
            setText(title);
            setDebounced(title);
            begin();
          }}
          className="max-w-[360px] truncate font-semibold text-accent text-page"
        >
          {title}
        </button>
        <Button
          aria-label={words.profileRenameTip}
          title={words.profileRenameTip}
          onClick={() => {
            setText(title);
            setDebounced(title);
            begin();
          }}
          className="size-7 min-w-0 px-0"
        >
          <Pencil aria-hidden className="size-3.5" />
        </Button>
        {note ? (
          <span role="alert" className="text-caption text-status-danger">
            {note}
          </span>
        ) : null}
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2">
      <input
        ref={input}
        aria-label={words.profileRenameField}
        value={text}
        maxLength={120}
        onChange={(e) => change(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") void apply();
          else if (e.key === "Escape") cancel();
        }}
        onBlur={cancel}
        aria-invalid={!!problem}
        className={cn(inputClass, "w-[260px]", problem && "border-status-danger")}
      />
      <span role={problem ? "alert" : undefined} className={cn("text-caption", problem ? "text-status-danger" : "text-text-tertiary")}>
        {problem || words.profileRenameHelp}
      </span>
    </div>
  );
}
