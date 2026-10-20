# Changelog

All notable changes to Roundtable Souls. The version is shown in the window title.

## [Unreleased]

- Saves: drag and drop. Drag a character (from its grip) onto a slot, an empty slot or a save card; a Library copy or a backup onto a live save to restore it; a live save onto the Library (save a copy) or the Backups (back up now); a Library copy expands to its characters, which drag into slots. Ctrl+C on a character and Ctrl+V on a slot do the same copy. Every drop is the same action as its menu entry (same confirmation, back-up first, re-sign, read back, Undo); a refusal says why at the drop spot and after the drop. Esc cancels, the page scrolls at its edges, and Explorer files still import.
- Mods: dragging a row now says why a drop is refused, in words at the drop spot (red line), the page scrolls when the row nears an edge, Esc cancels the drag, and a running job refuses the move with a message. The spots are judged in memory while you drag; the real check runs on drop.
- The packaged build now ships the QtQuick.Controls module, so the shared tooltip exists in it.
- The packaged build's self-test no longer trips over the shared tooltip or a page whose adapter is not ready yet.
- Importing a profile or a full export now asks when a mod has the same name as one you have installed but other
  files: the card shows what differs (files changed, added, missing, with sizes), a version label for each copy (from
  the download's name, a version file, a manifest or the README; never a guess from dates), when yours was installed and
  which profiles use it. Pick Use the incoming copy (into the current profile it replaces the folder in the same
  operation; Undo import brings your old one back byte for byte), Keep mine, or Keep both (name-2). A folder another
  profile also lists is never replaced: this profile gets its own copy beside it. Import waits until each is picked,
  unless the incoming version number is higher (then it is suggested).
- Importing into the current profile never adds a second entry for a folder the profile already lists (same mod,
  reused or replaced): the existing entry is kept, takes the incoming options and load order (Keep mine leaves it as
  it is), and the incoming mod's load_after / load_before references point at it.
- Keyboard and screen readers in the new window (UX pass): icon-only buttons (a mod's gear and bin, the header's
  folder, profile and More buttons, the log's chevron) have a name a screen reader reads, and Tab shows their tooltip
  as the mouse does. The hint bar's labels and the "Empty slots" line use the secondary text colour, which passes
  4.5:1 on the light theme (the tertiary grey was 3.5:1 there).
- Top bar and Mods list at narrow widths (UX pass): under 820 px the status (why Launch is blocked, what is running)
  gets a line of its own under the bar, with its fix link, instead of only a coloured dot; the status text gives way
  with a tooltip before its link does, and the link is reachable with Tab. A mod's tags and its status line ("Folder
  missing", "after flora") show at every width, and "Edit as text" keeps its label down to 760 px.
- Dialogs in the new window (UX pass): a long tick-box label (the New profile dialog's Seamless Co-op line) wraps
  instead of running off the dialog's edge, and the first field's focus ring is no longer cut by the dialog body.
- First run in the new window (UX pass): with no profile at all, the Mods page says what a profile is and offers a
  "Create a profile" button (before: a bare "Pick a profile first." and the only hint was in the top bar). The
  first-run "Launch" hint waits until Launch can actually start, so it no longer covers the page text.
- Plainer words in the new window (UX pass): the Launch pill says "Game program missing: eldenring.exe" and
  names the missing me3 in plain words instead of "game exe set on Tools"; the Mods page calls the second list "DLL
  mods"; the Remove and Delete confirmations no longer quote profile file syntax ("[[packages]]", ".bak",
  "load_after"); Profile settings, Versions and an empty "Add existing" end with Close, not Cancel, because there is
  nothing left to cancel.
- The old Widgets window is gone, with the hidden `--widgets` switch and the fallback to it. The Qt Quick shell is the
  only window. A failed start and a Steam-shortcut Play that did not start show a small Qt Quick message window. The
  PySide6-Fluent-Widgets library (and its helpers) is no longer part of the program, so the download is smaller.
- A rebuild of an engine mod (the overhaul and the like) that is interrupted at the very moment the new build replaces
  the old one no longer leaves the mod folder missing: the next start puts the old build back. A folder you delete
  yourself stays deleted.
- Importing a full-export zip unpacks each mod once, straight into its place next to the final folder (before, every byte
  was written twice, first into a temporary folder). The preview no longer unpacks the zip, the import checks for free
  space before it writes, and the page shows how much has been unpacked.
- Undo import of a profile the import created now removes the whole profile and every folder it copied, Seamless
  Co-op's copy included (before, the co-op entry and its folder were left behind). The co-op guard still protects
  your own profiles. Export opens on the small share list; the Full export tab shows its size.
- Importing a profile or a full export no longer copies a mod you already have: a mod folder byte-identical to an
  installed one (same files and sizes, then checksums) is reused, the new profile points at it, and the preview says
  so and how much copying it saves. Only a folder that differs is copied, as name-2. Undo import never touches a
  reused folder. (Before, importing your own export beside the original copied every mod again.)
- Export / Import profile, Export: a full export shows a progress bar (percent, file N of M, the file, MB done of total,
  time left) and a Cancel export button that removes the partial zip; it runs as a job, so it is in Activity. Export
  is off with the reason beside it, and a missing name, folder or mod is marked in place. A line says what the file
  will hold and its size; mods of 1 GB or more carry a warning badge, a total over 2 GB shows a warning naming the
  biggest mods and asks once before exporting. When it ends the page says Done (name, size, time, Show in folder),
  Cancelled, or what failed. Already-compressed files (.dcx, .bdt, .dds, archives, images, audio) are stored, not
  deflated: much faster for big exports.
- New Mods window, Rename: right-click a mod and choose Rename... to give its folder (and, for a package, its id) a
  new name. The profile's entry, the mods that load after or before it, the keep-after list and a DLL's attached
  config files follow, as one step with Undo. It is refused, with the reason, while the game runs, when another
  mod, another profile, an overhaul, Seamless Co-op or the mod that must stay last uses the folder, or when the name
  is taken or not allowed. The merged files are rebuilt before the next Play.
- The new interface is the launcher. One window with a menu bar (File, Profile, Game, Saves, View, Help), a top bar and a
  navigation rail: Mods, Mod Configs, Saves, Activity, and Settings at the bottom. The top bar has the Launch pill (the
  mode word picks Profile, Offline or Vanilla, remembered per game; Ctrl+L launches, Ctrl+Shift+L opens the mode menu),
  the game drop-down, the profile drop-down (New profile... last) and one line of status: Ready, the running job,
  "Elden Ring running", why Launch is blocked with a link to the fix, a dead game process with Clear, Steam not signed
  in with Open Steam, unsaved co-op settings (they apply on launch). What moved: Play became the Launch pill, Co-op
  became Mod Configs, Maintenance became Saves. Ctrl+1 to 5 open the pages, Ctrl+Tab changes game, Esc backs out of a
  sub-page. The old window is still there for now: start with `--widgets` to open it, and it opens by itself if the new
  one cannot start.
- Launch asks before the game starts when it must: a failed backup (Retry, Launch without backup, Cancel), merged mods
  that are out of date (Rebuild now, Play anyway this once, Cancel; with automatic rebuilds on it says "Updating merged
  mods..." and "Stop after the rebuild" lets the rebuild finish, then does not start the game), and a profile that would
  go online with changed game data (Launch Offline instead, Launch online anyway, Cancel). Launch Vanilla starts the
  game through Steam with no profile and no me3. Unsaved Seamless settings are saved first.
- Seamless Co-op left in the game folder: a bar on Mods offers Move into this setup or Clean up the game folder. Cleaning
  up never removes the settings file or the locale folder.
- File > New profile, Add existing profile, Import and Export profile; Profile > Fix load order is enabled only when the
  mod that must stay last is not last. The window frame follows the theme and keeps Windows' own corners and Snap
  Layouts. The self-test now builds the new window in all three themes at two sizes.

- Install mod, with "Install overhauls with the launcher (preview)" on: a download that ships its own installer, an
  me3 profile, or a regulation.bin with DLLs starts with "Set up as an overhaul" ticked and the reason shown; any
  other mod can tick it. The dialog shows what it will do (the Name gives the id) and the button reads "Install as
  overhaul"; Undo takes it back. A download an overhaul config already describes (such as the overhaul) is shown as
  already set up; one whose version is not listed is refused with the way out. With the switch off the dialog has
  no overhaul option, only one line naming the switch.
- The new Mods window installs mods in its own Install mod dialog (From archive or DLL, From folder, or files dropped
  on the page; several drops open one dialog after another, each once the last install has finished): the folder
  name (and id for a package), what to install, where regulation.bin goes and the mod that must stay last, as in the
  old dialog. Cancelling leaves nothing behind.
- Install mod: a folder name Windows refuses (such as CON), one of the launcher's own folder names, or one that
  makes a path too long for Windows is refused in the dialog with the reason, before anything is copied (before, a
  too-long path failed only after Install). A name that matches an installed mod's folder in another case updates
  that folder instead of making a second one.
- New Mods window, Adopt into the library: More has Adopt into the library..., and a bar offers it the first time (Preview,
  Not now; the confirmation can stop the offer for that setup). Adopting moves a setup you already have (a folder of
  profiles and their mods) into the launcher's own folder, rs-<game> inside the profiles folder: mods go to
  packages and natives, profiles to profiles, every path in them rewritten and their comments kept. It is one
  step on one drive: nothing is copied or deleted, and if anything fails nothing moves. Entries outside the setup's
  folder, a DLL loose in a folder other mods share and a mod another game's profile uses stay where they are, and
  the preview says so; folders no profile uses stay unless you tick them. Undo adoption in Activity puts every file,
  profile and setting back, and says no (leaving everything) when an adopted profile changed since. A setup with an
  overhaul cannot be adopted yet. Installs and Combine for an adopted profile go into the library too.
- Mod Configs: a profile with an overhaul setup shows an Overhaul setup entry. It is a form for the DLLs (load early,
  load after the other DLLs, initializer), the settings files kept when the mod updates and which binders are merged;
  a hand-edited one shows what it does and Edit as text changes it; a verified one that comes with the launcher
  is read-only. Turn off makes the mod an ordinary mod again (Undo turn off in Activity). Add overhaul setup... (and
  Set up as overhaul... on a mod) sets any mod of the profile up as an overhaul, showing what it does before it does it.
- Export / Import profile, a first look at the new page (the Mods window's profile gear, and a button on the Mods
  page): Share list writes one small file with your mods, their order and options, the profile settings and your
  mods' settings files (the Seamless Co-op password is left out unless you tick it); Full export also puts the mods
  in a zip with a README and a changelog. Import shows what each file would change, with a tick per file, and
  writes the ticked ones as one change you can Undo from Activity. A share list matches mods by id (DLLs by file
  name) and skips the ones you don't have; a zip is imported into a new profile by default. An import never turns
  online play on, only takes a save file name that is a plain .sl2 name, never writes a save from a zip, and
  never writes a settings file outside the folder of a mod your profile has. A mod download that also ships a
  profile offers "Import it instead..." in the Install dialog. Paste in Mod Configs now uses the same merge.
- Saves, a first look at the new page: a button on the Saves page, Open new Saves window, shows the two live saves
  (Standard first) with their characters, the Library and the Backups grouped by day. A character's menu copies it into
  any slot of either save (or duplicates it in the same file); a save's menu backs it up, saves a copy to the Library,
  or replaces it with a file or a Library copy (the old file is kept first); Import takes a .sl2 or .co2 from disk
  or dropped on the page. Check & repair opens beside the page with the findings in cards, and a click on a
  character opens its sheet (read-only for now). Every write waits for the game to let go of the file, backs up
  first and offers Undo in a toast and in Activity. A whole file from another Steam account is signed for the
  account it goes into (profile summary, every character, all checksums) and read back before anything is written;
  this has not been tested in the game yet.
- Saves, in both windows: the repair notes for a stale character or profile-summary checksum now say what the game
  does with it (it refuses the save as corrupted), and every save write waits for the game to release the file and
  stops, with a message, if it does not.
- the overhaul's menu text now takes its languages from the game's own list and always starts from the game's own
  file, never the copies in the overhaul's download (which can be from an older game version); the output is the same
  bytes. Because the build's config changed, a the overhaul build the launcher made is rebuilt once at the next Play, and a
  language file missing from the game's archives stops that build with its name.
- A character script that uses a number above 16,777,216 that the game's 4-byte script numbers can't hold exactly now gets a warning (it
  would be rounded); the build still goes ahead.
- Whether the game is running is now decided by its threads, not its memory: a game that is still starting (even one
  held back at launch) counts as running, so saves and mods are not touched while it comes up; only a leftover copy
  with no threads counts as a dead shell.
- Settings, a first look at the new page: a new button on the Settings page, Open new Settings window, opens
  Locations (with a saves folder override, per game), Launch, Backups, Appearance, Updates, Logs and About. New
  settings: how many backups are kept per save (5 to 200, default 20; the last 7 days and any Keep stay), the
  theme (Dark, Tarnished, Light or System; the older window shows Tarnished as Dark and System as the OS scheme),
  Effects, Grain and Log level (Verbose writes the fine detail to launcher.log from the next start). Update offers,
  downloads and Restart now show in both windows and run the same checks as before. Boot boost, Repair saves and
  Offline play now say what the game does and does not do.
- Play offline now always turns online play off in its temporary copy of the profile. Before, a profile set to
  go online (start_online = true) went online during an offline launch.
- New profile asks what to start from: an empty profile, or a copy of any of the game's profiles (before, only the
  current one could be copied).
- The new Mods window has a profile picker in its header: every setup on the Play list, picked there as on Play.
- New Mods window: a warning when the profile goes online with a mod's parameters (regulation.bin), with Play
  offline to turn online matchmaking off (Undo puts it back); the Parameters card shows a fingerprint of the
  parameters the game will use, with Copy, so co-op partners can check they have the same; and, with the overhaul
  preview on, More has Install an overhaul with the launcher, Remove <overhaul> and Clean up installer leftovers,
  as the Overhaul button does. It also puts right a change that was interrupted, as the Mods page does.
- Delete profile: a profile an overhaul's own installer set up is refused whichever way it was picked (before, its
  .me3 could be deleted directly). A profile the launcher installed an overhaul into can be deleted; the confirmation
  says the overhaul's shared files stay. Removing an entry that only points at a folder of mods is now one change
  to the profile (one backup, one entry in Versions).
- Mod Configs, a first look at the new page: a new button on the Co-op page, Open new Mod Configs window, lists the
  profile's mods that have settings files, Seamless Co-op first. An .ini, .cfg or .toml file opens as a form (a
  switch, a list or a number per setting, the file's own comment as help, Reset to a default the comment states);
  any file can be edited as text. Save changes only the values you edited: comments, order and spacing stay, and
  a file changed elsewhere since it was opened is not overwritten. Seamless Co-op has its own panel: password,
  difficulty, language (the game's, or a translation in its locale folder) and Share with a friend (Copy, Paste,
  Load and Save settings as plain ini lines; a pasted older JSON export still reads; the parameters fingerprint).
  In the new Mods window, a DLL's file icon and Mod options' Open on Mod Configs open it on that mod.
- Remove overhaul no longer leaves empty builds, overhauls or sources folders in the launcher's library folder.
- Combining parameter packs that add many rows is much faster: 66,000 added rows took about 5 minutes, now under
  a second.
- Install mod: a mod that ships game files and DLLs together now gets both kinds of entries. Before, it was installed
  as a package only and its DLLs were never loaded. Only the DLLs directly in the mod's folder are added (you can
  untick them); DLLs in its subfolders stay part of its files, and settings files beside its DLLs are grouped as
  settings.
- Install mod: a download that is only a me3 profile now gets its plain message ("This is a whole me3 profile, not a
  mod...") instead of an error.
- The launcher's own files beside a profile now live in one hidden .roundtable folder: the profile's launcher
  settings (before, roundtable.json), its .bak, the records that let an install be finished or undone, and the copy
  of a mod kept after an update (before, a .previous folder beside the mod). Nothing is moved: roundtable.json is
  copied the first time it is read and left as it is, older .bak files and records stay where they are and are still
  read, so an older launcher keeps working with the same folder.

## [3.22.0] - 2026-10-15

- the overhaul, a preview you turn on (Tools > Play session > "Install overhauls with the launcher (preview)"):
  the launcher can install the overhaul LITE 0.1.33 into a profile itself, from the folder you unpacked its download into,
  without running its installer. The Mods page's new Overhaul button shows everything that will change first: the
  profile's new entries (with paths relative to the profile), the settings it changes (start_online), and the copy of
  the download it keeps. It's one step you can undo from Activity; if anything fails, nothing changes. Installing again
  is an update (Activity can roll it back), a profile that already has another overhaul is refused, and a the overhaul that
  its own installer set up isn't touched: remove it first. The launcher keeps its copy of the download and its notes
  in its own folder, rs-eldenring, in me3's profiles folder; the overhaul's own folder stays beside your profile as before.
- Remove overhaul (same preview): one action takes the overhaul out of a profile. Its entries go, and each setting its
  install changed is put back, but only where it's still what the install set; anything you changed since stays, and
  the preview says so. Its folder, its build and the launcher's copy of its download go to the Recycle Bin when no
  other profile uses them. Seamless Co-op is never removed. Restore in Activity puts it all back. For a the overhaul that
  its own installer set up, the launcher compares your profile with the installer's oldest backup and lets you pick
  which of its changes to put back. Then Clean up installer leftovers offers its leftover folders with their sizes:
  the setup copy first, and its "the overhaul Backups" separately at the end, since that's the only copy of your profile
  from before the overhaul.
- the overhaul: the launcher now reads a download's edition and version from its edition.json, which every
  download has, instead of the file only the overhaul's installer writes. So it recognises a download straight from its
  archive. If you use "Build the overhaul in the launcher (preview)", this counts as a change: the next Play
  rebuilds the overhaul once (or asks first, if you turned off automatic rebuilds before Play).
- Combine and overhaul builds match a merged archive's inner files the way the game finds them: by ID in part,
  character and texture archives (where a mod may rename every inner file and still work), by name where the ID is
  only a position. Two mods changing the same part now meet on it instead of being listed under different names.
  Merged builds are rebuilt once.
- Combine and overhaul builds now say when a mod's copy of a merged archive lacks inner files the current game has:
  "Sekiro Animations lacks 58 animations the current game uses (they won't play)". A notice in the build's report and
  log, not a stop.
- the overhaul (launcher build): a character script using Havok Script's own syntax (`hstructure`, `hmake`,
  `0x…hi` numbers) is no longer refused as a syntax error; the build's report names the line the check can't read.
  Real syntax errors are still refused, and so are `0x…hl` numbers, which the game never compiles.
- Combine and overhaul builds check parameters the way the game reads them: a result with more than 65,535 rows in a
  table, or missing a table the game's own regulation has, is refused (the previous build stays); a table the game
  doesn't know and rows with negative IDs are warnings in the build's report.
- Merged talk scripts: a mod's talk commands and functions the game doesn't have are warnings in the build's report,
  naming the mod, the state machine and the state.
- the overhaul (launcher build): the build's report warns about calls of functions defined nowhere the game
  looks and `env`/`act` IDs the game doesn't handle. Functions a mod's own DLL provides can't be seen by the
  launcher, so the warning says so; the overhaul's config names its own (OverhaulNative), and a call the script makes only after
  checking the function is there (the overhaul's use of Nightreign Movement's) isn't reported.
- Play: going online with a mod's parameters is warned about before the game starts. After Play, when me3's fast DLC
  loading failed, the log says so in plain words: "me3's fast DLC loading failed this launch; if your DLC was
  missing, that's why; Play again."
- Mods: a first look at the new design. A new button on the Mods page, Open new Mods window, opens the redesigned
  Mods page in a window of its own: the mods in the order me3 loads them, switched on and off in place with Undo,
  dragged into a new order (a move me3's load-after rules would undo is refused and says why), Mod options, Profile
  settings, Versions, the Parameters card and the Load order panel. The Mods page you know stays as it is.
- Mods: removing an entry that only points at a folder of mods no longer fails when another mod must load after
  it; deleting a profile now waits until the running job finishes; a mod's rebuild tool is asked about again when
  its program or script changes. Wording: refusing to delete a profile an installer manages names that profile.
- Combine and overhaul builds are much faster: merged archives are compressed at Oodle level 4 instead of 6. The large
  effects archive takes about 5 seconds instead of nearly 2 minutes, for about 3% more disk; checked in game with the
  same effects and load time.
- Linux and Steam Deck: without the game's Oodle library, any merged file can now be written in the zlib format the
  game also reads (it was limited to text, animation and effect archives; another file type was checked in game).
- Play: with no profile for a game yet, a Get started card creates one in one click, in its own <game>-mods folder,
  and offers to bring in Seamless Co-op from the game folder (its launcher is removed, with a warning).
- Mods: New profile puts each game's profiles in its own <game>-mods folder with its own mod and natives folders (they
  were shared between games). A profile made as a copy now sits beside the original, so its mods keep working (the
  copy's paths pointed at the wrong folder before).
- Play session: Elden Ring's "Repair saves after quitting" is now off by default and has its own setting. The game
  never reads the save's regulation section back, so only save editors need it; turn it on under Tools > Play session
  if you use one. Nightreign's repair, which re-signs its save sections, stays on.
- Co-op: when Seamless Co-op is installed in the game folder (where its own installer puts it) and your profile
  doesn't load it, the Co-op page offers to move it into your setup and add it to the profile, settings and password
  included. When your profile already has its own copy, it offers to clean up the old one instead. Seamless Co-op's
  own launcher (ersc_launcher.exe / nrsc_launcher.exe) is removed either way, with a warning; everything removed goes
  to the Recycle Bin. "Not now" hides it until next time, "Don't ask again" for good. Elden Ring and Nightreign.
- Activity: a first look at the new design. A new button on the Activity page, Open new Activity window, opens the
  redesigned Activity page in a window of its own: the last Play, install and failure at the top, the jobs by day,
  each job's log one click away, and Undo, which asks before it changes anything. The Activity page you know stays
  as it is.
- the overhaul (only with "Build the overhaul in the launcher (preview)" on): its build now notes which game
  version and which config it was made for, so it is rebuilt before Play when the game is updated ("the game was
  updated since the last build") or when its config changes what the build does ("the overhaul's config changed
  since the last build"). A build made before this version doesn't say, so it is rebuilt once, the first time you
  press Play.
- Overhaul configs (for mod authors): a build can say where its download's files go in the launcher's own layout,
  `[builds.sources]` (what its builds read: merge, text, hooks, base) and `[builds.runtime]` (what it runs with). They
  are checked when the config loads; nothing uses them to install yet. docs/Overhaul configs.md has the details.

## [3.20.0] - 2026-10-09

- Appearance: new colours, the first step of the new look. Dark is now a near-neutral charcoal with the gold as its
  only colour (it was brown), with quieter lines between parts; light keeps its Carian blue with softer lines, and
  secondary buttons in both themes have no fill until you point at them. Code in the editors is highlighted in the
  same colours, with keywords in green so they read clearly. Layout and behaviour are unchanged.
- Mods: the conflict list names what each file is in plain words (the player character's animations, behaviour
  scripts, text, parameters, ...) instead of its folder.
- the overhaul (only with "Build the overhaul in the launcher (preview)" on): merge-report.txt says what
  each clashing file is, licence and notice files a download ships are kept next to its DLLs, and the build's
  installation.json records the edition. The build no longer refuses to start without Seamless Co-op switched
  on: what a mod needs is for its author to declare, and the launcher no longer decides it for the overhaul.
- the overhaul (same preview): the character script the build puts together is checked before it is used. One
  that the game could not load is refused when you build, naming the line and whose script it is, instead of the
  downed and overhaul states silently not working in game; the previous build stays.
- Overhaul configs (for mod authors): what an overhaul needs is a `requires` list on its build (the build is
  refused without it, and the launcher keeps it switched on while the overhaul is), and a script
  fragment is added with `do = "hook"` (several in order, each wrapping the one before). A config you made yourself
  with `[builds.install.seamless]` or `do = "script_append"` is left out until it is updated, and the launcher says
  which key moved where; docs/Overhaul configs.md has the new form.

## [3.19.0] - 2026-10-08

- Mod configs: the last place that said "tie" now says "attach", like the Attach and Detach buttons.
- Mods: every change the launcher makes to a me3 profile now goes through one writer with one set of rules. New:
  a profile edited outside the launcher (a text editor, another tool) after the launcher read it is never
  overwritten; the change is refused with "the profile changed outside the launcher; reload and try again". Also
  refused, as me3 would refuse to start: a change that makes a package id appear twice, loops the load order, or
  switches on two DLLs with the same file name (both are named). Problems a profile already had do not block other
  changes.
- Profile history: two changes made within the same millisecond are listed in the order they were made
  (the newer one could show as the older).
- Mods: two launcher windows can no longer write the same profile at the same moment: a change waits briefly for
  the other window's install or removal to finish, then says so instead of writing. Undoing a removal lists the
  restored mod under the mod that must stay last again.

## [3.18.0] - 2026-10-08

- Mods: installing, updating and removing a mod are now each one step that can't be left half-done. The new files
  are prepared beside the old ones and your profile's new text is worked out first; only then is everything swapped
  in together. If the window or the PC closes in the middle, the next start finishes or undoes it, and Play waits
  until it has.
- Mods: an update keeps the previous version. Activity offers Roll back (folder and profile back as a set), and a
  fresh install can be undone (your profile exactly as before, and only the files the install added are removed).
  Files of the mod you had changed yourself (an ini, say) are kept; the new version's copy is put beside them as
  .new, and the log says which.
- Mods: when "rebuild after installing" is ticked, the rebuild is part of the install: if it fails, the whole install
  is undone and the previous setup stays as it was.
- Mods: removing a mod never deletes a folder that holds Seamless Co-op's DLL, even when this profile no longer lists
  it (another profile may still use it).
- Combine: archives the game lists in ID order (its effect archives, for example) keep that order when a mod adds
  files to them, as the mods' own tools write them. A combined package merged with an earlier version is rebuilt once.
- the overhaul (only with "Build the overhaul in the launcher (preview)" on): the launcher now merges the
  grace menu itself too, and runs nothing from the overhaul's download (no Assets.exe). Two mods shipping different
  character scripts, and a compiled script that the overhaul's script can't be added to, are reported instead of silently
  replaced; clashes go to merge-report.txt. The launcher's own build no longer asks for rebuild-tool permission. The
  preview's description no longer claims a recorded comparison with the overhaul's installer: that check now exists as
  scripts/verify/native_parity.py, and its in-game half is still to come.
- Under the hood: one profile reader for every part of the launcher, the overhaul described in one data file
  (data/overhauls), and the game's locations handed to every mod operation; no change in behaviour.

## [3.17.0] - 2026-10-06

- Combine: animation events (TAE files, such as the player's in `chr/c0000.anibnd.dcx`) that several mods change are
  merged animation by animation: a mod that changes some animations (a dash mod's dodge rolls) and one that adds
  others (the overhaul's downed and overhaul animations) now both apply, instead of the later mod's file winning
  whole. The same animation changed differently by two mods goes to the later one, and the record says so. Events
  inside one animation are not merged. Checked in game with a dash mod and the overhaul. A combined package that
  merged files with an earlier version is rebuilt once.

## [3.16.0] - 2026-10-05

3.15.0 was never published (its release build stopped), so its changes, listed below under 3.15.0, reach you with
this version.

- Backups: a backup whose note is damaged or was cut off half-written is never removed by the automatic clean-up, and
  the Saves page shows it as "Protected: metadata unreadable". Notes are written so an interrupted write can no longer
  damage them, and keeping a backup "for good" keeps the rest of its note.
- Backups: two launchers at once (the window and a Play from a Steam shortcut, say) no longer race when a backup is
  taken, kept, restored, deleted or cleaned up.
- Save library: a library.json that can't be read is reported and left as it is, instead of being replaced by an
  empty library. Two launchers changing the library at once no longer lose each other's changes, and fields a newer
  version wrote are kept.
- Save library: a swap whose history could not be written still counts (it is added later), and a copy whose removal
  stopped halfway can be put back or its removal finished from the Saves page.
- Play: with "Back up saves before Play" on, a failed backup no longer starts the game without asking. The window
  offers Retry, Launch without backup or Cancel; a Steam shortcut stops with a notice unless it was started with
  --allow-without-backup.
- The launcher now keeps its file-hash cache and its activity log in a small database, roundtable.db in its data
  folder. Existing records are imported the first time; the old files are left in place, so an earlier version still
  works if an update is rolled back. Activity entries are kept for 90 days. Undo records stay where they were.
- If the database can't be used (another launcher is updating it, it comes from a newer version, it is damaged, or
  the disk refuses), the launcher works as before without it; only a failed upgrade of the database stops start-up,
  so a bad update is rolled back to the version that worked.
- Under the hood: the code was reorganized into clearer packages (no change in behaviour), and releases are built
  with Python 3.14.7.

## [3.15.0] - 2026-10-02 (not published; included in 3.16.0)

- Load order: the launcher now works out the order exactly as me3 does (the same steps, checked against me3's own code on more than 100,000 profiles), so the file a mod wins or loses is shown right. Before, a mod placed with load_after could be shown in the wrong place. Mods named in another mod's Load after list load in that list's order. Switched-off mods take part in the order as in me3, mods whose folder is missing are left out, and a profile me3 would refuse (a loop, or a required mod that is missing, missing its folder or named with different capital letters) is shown as such on the Load order card.
- Load order: when the installed me3 is older than 0.11.0, the Load order card says the order shown was not checked for that version.
- Files the launcher writes with ZSTD compression all use the frame the game reads (a 64 KB window), as regulation.bin already did.
- Without the game's Oodle library (Linux), menu text, player animations and effects are written as DFLT, which the game loads, instead of stopping. Reading the game's own Oodle-compressed files there still needs Oodle.
- Combine: the combined-parameters package is added to the Load after list of the mod that must stay last, so me3 loads it before that mod.
- Combine: a rebuild is written beside the combined-parameters folder, every file is read back, and only then put in place; a rebuild cut off part way (a crash, a power cut) is undone the next time, so the previous result stands. It is not put in place while the game runs, and it does not start when the drive lacks room for it.
- Combine: grace menus and other talk scripts that several mods change are merged: each mod's menu options, new states and new menus are kept (a state number two mods both use is given to the later one anew), and parts only one mod changed come from that mod. Where mods change the same part differently, or add the same menu option, the later mod's script is used whole, as before, and the record says why. Checked in game with two mods that each add grace menu options. A combined package that merged files with an earlier version is rebuilt once.
- Combine: the record lists, file by file, inner files a mod's copy leaves out (they are left out of the result, as before), and says which merging rules, load order model, game data and me3 version made it; a change in the rules makes it out of date. Two inner files whose names differ only in capital letters stop the merge with the reason.

## [3.14.0] - 2026-10-01

- Play: the game no longer starts with merged mods that are out of date without asking. When they cannot be rebuilt first (the rebuild tool was not allowed or failed, or something stops it), Play asks, and Play anyway starts it this once. A Steam shortcut or Gaming Mode does not start the game then and shows why, with a way to open Roundtable Souls.
- Settings: "Update merged mods before Play" is now "Rebuild merged mods automatically before Play". On (as before) it rebuilds first; off, Play asks first instead of starting with the old result.
- Mods: Remove and Restore have one button. Files of a removed mod that are still inside the merged mods are named, and Play rebuilds them first (or Rebuild on the Mods page). Load order names the removed mod instead of its folder's inner folder.
- Mods: a mod's rebuild tool that has not been allowed yet is offered on the Mods page, so a rebuild does not stop in the middle to ask.
- Installing and updating now use Velopack instead of Inno Setup and the launcher's own file swap. The program is a folder rather than a single exe, so it starts faster (nothing is unpacked to the temp folder first).
  - Windows: `RoundtableSouls-Setup.exe` installs for your account only, with no administrator prompt, to `%LOCALAPPDATA%\Carlomos7.RoundtableSouls`, and adds a Start menu shortcut.
  - Portable: `RoundtableSouls-win-Portable.zip` keeps its data in `RoundtableSouls-data` beside it.
  - Linux and Steam Deck: an AppImage, `RoundtableSouls-linux-x86_64.AppImage`.
- Settings, logs, backups and the save library never live in a folder that an update or an uninstall replaces. Installed copies (and the AppImage) keep them in `%LOCALAPPDATA%\RoundtableSouls` (Linux: `~/.local/share/RoundtableSouls`), as before; a portable copy keeps them beside it in `RoundtableSouls-data`; `ROUNDTABLE_SOULS_DATA` points any copy at a folder of your choice. Uninstalling leaves them alone.
- Moving from the old installer happens by itself at the first start of the new one.
  - The old install (3.13.2 or earlier) is removed. Settings, logs and backups stay where they are.
  - The Start menu shortcut, and the desktop shortcut if you had one, are recreated for the new copy.
  - Steam shortcuts that started the old program now start the new one; a backup of Steam's shortcut file is kept.
  - If Steam is open, that last step waits: close Steam, then use Settings > Steam shortcut > Point Steam shortcuts here.
  - Versions up to 3.13.2 reach this release through Update now (installed copies). Portable and Linux copies are updated by downloading it from the releases page.
- Updates are signed. Update now installs only what this system's signed feed lists: the signature must check out with the project key built into the launcher and name this release and system. Every package must match the size and SHA-256 in that feed before it is applied. When this copy is exactly one version behind, only the changes are downloaded. A release that is not newer than the running copy is refused.
- Updates undo themselves when the new version does not start.
  - Before an update, this version is kept. The new one must open its window, or get a Play from a Steam shortcut going, within 90 seconds.
  - If it does not, the kept version is put back and started, and says so.
  - The failed version is never installed again. A newer release is offered as usual.
- `RoundtableSouls --update` updates without the window (a terminal, or a Steam shortcut in Gaming Mode), then starts the launcher; `--update --game er --play` starts Play instead.
- A check that could not reach GitHub (offline, GitHub's hourly limit, an error) now says so and why, on Settings and after Check for updates, instead of reporting "up to date". Settings shows when the last check succeeded.
  - After failed checks the automatic one waits longer each time (up to a day); Check for updates always asks at once.
  - Unchanged answers are asked for with the previous answer's tag, which GitHub does not count against its limit.
- The update notice shows the start of the release notes and a Notes button. Settings has an update channel: Stable (as before) or Beta, which also offers pre-releases. The project can publish a notice asking versions with a known problem to update (it only warns).
- One window: starting Roundtable Souls again brings the open window forward. Play from a Steam shortcut while the window is open runs Play in that window; a second shortcut Play while one runs is refused; Update now waits while a shortcut Play runs. Two copies with separate data (an installed and a portable one) can still run side by side.
- Settings are written under a lock, so a change made at the same moment as the update check (or a Steam shortcut Play) writes is no longer lost.
- Steam shortcut (Settings): Point Steam shortcuts here makes every Steam shortcut with `--play` that starts a Roundtable Souls program elsewhere start this copy (Steam must be closed; a backup is kept). The shortcut target shown is the launcher's stub (or the AppImage), whose path stays the same across updates.
- Fixed: when the launcher changes a file inside an archive in place (the menu text of the preview the overhaul build), the archive now records that file's new size instead of the size it had before. Archives the launcher does not change are written exactly as before. Not yet checked in game.
- Inside: parameters and archives are read and written by one shared piece of code (the game's own files come back byte for byte), and the launcher can read and write talk scripts such as the grace menu (checked on every one in the game; not used by merging yet).

## [3.13.2] - 2026-10-01

- Fixed: combined parameters (regulation.bin) written by the launcher crashed the game at start. The file is now compressed with a 64 KB window, the frame regulation editors write; checked in game on Windows with Elden Ring 1.17.1, together with each layout the launcher can write for merged archives and text.
- Versions 3.6.0 to 3.13.1 use the same compression settings for combined parameters as the writer that crashed. The crash was reproduced with that writer on Elden Ring 1.17.1; the older versions themselves were inspected, not run in game. Combining parameters only happens when two enabled mods both ship a regulation.bin, or in the preview the overhaul build.

## [3.13.1] - 2026-09-30

- Fixed: Oodle-compressed files the launcher writes (merged files, and the preview build of the overhaul) now use the tested Elden Ring layout: compression level 6, with the same level in the file header. Files over 16 MB were written at a faster level with that level in the header, a layout no game file uses. Merging the largest archives now takes longer (the 88 MB effects archive about two and a half minutes instead of seconds).
- Mods: a DLL's settings files are attached rather than tied: Attach a file and Detach.
- Mods: Rebuild is offered whenever a build exists, so turning on Build the overhaul in the launcher can be put into effect at once.
- Look: a new light theme, frost and Carian blue with snow-white cards; dark keeps its gold. Status colours, pills (now with a mark: ✓, ✕, ⚠), logs, dialogs, menus and the sidebar follow the theme; a page's main action is solid, a destructive one is red; the sidebar can be reached with Tab.
- Mods: Install mod asks archive or folder first; cancelling a picker installs nothing.

## [3.13.0] - 2026-09-30

- Mods: files two mods both ship are merged, not just replaced. For archives (menu layouts, animations, effects and the like) and text, a Combine or Rebuild reads the game's own copy from its archives, works out what each mod changed, added or removed inside, and puts all of it into one file in the combined package, so both mods apply; where two mods change the same part, the later one's is used and the log says so. Load order shows those copies as combined, and a changed copy or a game update makes the merge out of date (Play updates it first). Undo rebuild covers the merged files too.
- Mods: building the overhaul in the launcher (the preview on Settings) now merges its animations, effects, menu text and parameters with the launcher's own merger instead of the mod's tool; only the grace menu still uses the mod's tool. On a real profile the content matched the mod's installer's, file for file.
- The game's own files are read from its archives when a merge needs them; the decrypted archive indexes are kept in the launcher's data folder after the first time.

## [3.12.0] - 2026-09-30

- Mods: the launcher can build the overhaul (LITE 0.1.33) itself from the download kept in its setup folder, instead of running its installer (Build the overhaul in the launcher, on Settings; a preview, off by default). It follows a recipe (data, not code) and uses the mod's own merge tool for each merged file; on a real profile its output matched the installer's file for file. The profile is never rewritten, OverhaulPrototype.ini keeps the player's values (a newer version only adds its new settings), inputs are only read, a failed build leaves the old one in place, and the build it replaced is kept for Undo rebuild instead of a full backup on every run. Other versions still use the mod's installer.
- Docs: the recipe format, in Rebuild tools.

## [3.11.0] - 2026-09-29

- Play: when merged mods are out of date (a mod was added, removed, turned on or off, reordered or updated, or the game updated), Play rebuilds them first and then starts the game, with Cancel Play. A failed rebuild keeps the previous result and offers Play anyway or View details; it is not retried with the same mods in that session. Offline Play and Play from a Steam shortcut do the same (the shortcut only runs a rebuild tool that was already allowed, and starts anyway on failure).
- Play: after an automatic rebuild only the newest 3 of a rebuild tool's backups are kept (about 140 MB each for some tools); older ones go to the Recycle Bin.
- Settings: Update merged mods before Play (on by default). Off, Play only warns as before. Load order says an out-of-date merge will update at the next Play.

## [3.10.0] - 2026-09-29

- Mods: the package that must stay last (and its DLL) now stays last however mods are added. Installing, adding existing folders, removing, renaming an id or saving options keeps its own load_after lists naming every other package and DLL (on or off, each optional), so switching a mod on or off never rewrites them; your own entries are never changed. New mods go right before it in the file.
- Install: with such a package, the dialog says a new mod is placed before it so it includes the mod's changes, instead of offering a load order; an advanced option loads a mod after it on purpose.
- Load order: a Stays last section says when a mod loads after it (an edit by hand) and replaces its files, with Fix order and Keep it after (and Put them before to undo that). A change that would make the load order loop is not made, and the reason is shown.
- Profiles: the package set as the parameter overlay, and the mods kept after it on purpose, are kept in roundtable.json next to the profile (relative paths), so a copied profile folder works the same on another PC. A setting from an earlier version moves there on its own; a folder that cannot be written keeps using the launcher's own setting.
- Fixed: when the package that must stay last is there but its setup files are not, Load order names the missing files (installation.json, the setup folder) and how to put them back, instead of saying it loads after the combined parameters, and Rebuild stops before changing anything.

## [3.9.0] - 2026-09-29

- Fixed: removing a mod took the comment lines of the entry after it (a section heading, another mod's notes) and left its own behind. Removing now takes exactly the entry and its own comments, and a removed entry can be put back byte for byte where it was.
- Profiles: a copy is kept before every change the launcher makes (the newest 30, in the data folder, identical copies skipped). Switches, options and profile settings show Undo right after the change; Edit profile > Versions restores any copy, and a restore can itself be undone.
- Mods: removing a mod inside combined parameters offers Remove and rebuild, so the game does not keep a removed mod's changes; removal is a job on Activity. The folder goes to the Recycle Bin instead of being deleted (Windows still asks before deleting for good when the bin cannot take it), and Activity's Restore puts the folder and the entry back.
- Mods: Undo rebuild on Activity puts back what a rebuild replaced: the rebuild tool's output from its own backup and the launcher's combined parameters (the last 3 kept), swapped by renaming so it is instant and needs no space; Redo swaps them again. The profile comes back as it was before the rebuild.
- Mods: Load order shows how much space a rebuild tool's backups take (it never removes them) and can move all but the newest 3 to the Recycle Bin.

## [3.8.0] - 2026-09-29

- Activity: a new page in the sidebar listing every job (Play, repairs, installs, rebuilds...) by day, with how it went and a line on what it did or what went wrong. Open one for its log, with Show details for the fine detail and me3's output kept with each Play; filter by game, kind or failures. A red count on Activity shows jobs that failed since you last looked, and a failure message offers View in Activity. Copy for support and Save logs for support (a zip) mask your user name and Steam IDs. The Log on the Play page links to it.
- Mods: parameters are a green or red pill next to the profile name (Parameters OK, out of date, 1 of N apply, or rebuild failed). Clicking it opens Load order.
- Mods: Load order replaces Conflicts and explains what the profile loads from one scan: the parameters' status with reasons, Combine or Rebuild, and the rows two packs both changed; every file two packages ship with what happens to the earlier copy (replaced, combined, combined but out of date, or not reaching the rebuild), checked against the rebuild's or the combine's checksums; and the entries me3 would refuse. It opens by itself when the pill turns red.
- Logs: a job's end line reads "failed in 3s, 1 error" instead of counting zeros.

## [3.7.0] - 2026-09-29

- Logs: every job (Play, a repair, an install, a rebuild...) keeps its own log in logs\jobs, with how it ended, instead of one last_run.log overwritten by the next job. jobs.jsonl lists them. me3's output is kept with each Play instead of one file overwritten per launch. launcher.log (rotated) holds everything else and every crash with its details, replacing launcher-errors.log, which only grew. Jobs are kept for 14 days or the newest 50; older log files move to logs\old and go after 30 days.
- Logs: lines carry real levels (errors, warnings) and where they came from, with milliseconds. A job's log only has that job's lines; background checks no longer mix in. The Log on the Play page shows the running job and warnings from anywhere, wraps long lines under the message, and has a Logs folder button; its buttons wrap in a narrow window. Changes made in the window itself (profile options, co-op settings) are kept in launcher.log too.
- Logs: a folder the launcher cannot write no longer stops logging; the window still shows every line.

## [3.6.0] - 2026-09-29

- Mods: combine parameter packs. When several packages ship a regulation.bin, Combine on the Mods page (or the box in the install dialog) applies each pack's changes to the game's own file, row by row in load order, so all of them apply: packs changing different parts of a row both apply, overlapping values go to the later pack and are listed, rows a pack lacks are kept, and tables made for another game version are left out and named. The result is a launcher-managed package, combined-parameters, checked against what went in like any rebuild.
- Mods: with a package that must stay last and has its own rebuild tool, the combined package goes right before it, so that tool takes the combined file and every pack applies, not only the last one.
- Mods: merge health for Elden Ring profiles. When the package that must stay last comes with a rebuild tool that folds earlier packages' regulation.bin (and similar shared files) into its own, the Mods page says whether that merge is up to date, why not (a pack added, changed, turned off, reordered or removed, or a game update), and offers Rebuild. The tool is found from its files, never from a mod's name, and the launcher only runs and checks it.
- Mods: installing a pack with a regulation.bin before such a package offers to rebuild afterwards, notes which of the pack's files the rebuild will take, and warns when another pack stops being the source. Without a rebuild tool, placing a pack before the last one says its parameters will not apply; placing it last says the other one's will not.
- Mods: a rebuild saves the profile first, keeps your commented profile when the tool only rewrote it (updating just the tool's own load order lists), and is verified against the tool's list of sources; a run that did not use the right files is reported as failed. Play warns about out-of-date or failed combined parameters but never rebuilds by itself.
- Mods: rebuild tools are described in one documented format, rebuild.json (docs/Rebuild tools.md), so any overhaul can ship one: the command, what it combines and where it lists its sources. Tools that keep an installation.json with a refresh protocol are recognised as before. The launcher shows a tool's command and asks once before it first runs, and again when it changes.
- Mods: Parameter overlay in a package's Options marks it as the package that must stay last when the launcher does not recognise it by its files; its rebuild tool is then looked for with looser rules, or a rebuild.json can be picked for it. Nothing else asks for per-mod labels.
- Mods: a folder holding only a leftover regulation.bin no longer hides the real mod folder below it when installing.
- Mods: changed load order lists keep their place in the entry and their one-per-line layout.

## [3.5.0] - 2026-09-29

- Buttons: one size and shape everywhere; a primary action and the button beside it always match. Only Play stays larger.
- Save rows: the Co-op page, both text editors and Review & fix share one bar: a note on what is unsaved, Discard and the action. On a narrow window the note goes above the buttons.
- Editors: Edit profile and Share with a friend work the same way. The name of what the text came from, the tools, the editor, then Discard and Save (or Apply). Edit profile's Save moved from the top of the Mods page to under the editor.
- Closing the window or switching games with unsaved changes asks Save, Discard or Cancel. Before, closing could only save or stay open.
- Messages at the top of the window keep their buttons on a row under the text, so they fit a narrow window. Every dialog uses the launcher's own buttons.
- Mods: each package and DLL has a tag naming the folder it sits in, below the profile's natives and mod folders (the full path is on hover). Long names shorten on a narrow window instead of pushing buttons out of view.
- Mods: the packages folder (mod) and the natives folder show as folders at the top of their lists. An entry that points at a folder of mods instead of a mod (it loads nothing itself) is explained there instead of listed as a mod, with Remove entry; Not loaded lists the mod folders and DLLs in there that no entry points at, to add the ones you pick. Nothing is copied or moved. A profile with one package for everything, as in me3's guide, stays a normal package.
- Mods: removing an entry whose folder other entries still use no longer offers to delete that folder, and says why.
- Saves: the file Play uses follows the setup. A save file name set in the me3 profile and Seamless Co-op's save file setting are both honoured, so a renamed save is listed, and repaired after play, like the default one. The Saves page says which file Play and Play offline use.
- Saves: Copy to... replaces another save with a whole file (the save it replaces is kept in the library first, under a name you choose) or only adds a named library copy. Both show every character before and after.
- Saves: Copy a character... copies one character into a free slot, or over one, in the same or another save, checked and backed up; a character from another Steam account moves to this one.
- Saves: a save library keeps named copies of whole saves beside them. Swap in puts one in place of a live save and files the replaced one first, so nothing is lost. library.json records every copy, swap, rename and removal.
- Mods: each entry is checked the way me3 reads it: a missing file or folder, a native that is not a .dll, a package id used twice, a required load_after / load_before that is missing or switched off, and load orders that loop are named on the entry.
- Mods: Options offers only entries of the same kind for load order (me3 orders packages with packages and DLLs with DLLs), named the way me3 refers to them.
- Mods: Conflicts looks only at the game folders at the top of each package, which is what me3 serves; a folder of other mods no longer counts their files twice, and the scan is much faster.
- Mods: quieter rows: no On / Off text beside the switches, long load-order lists shortened (the full list is on hover), initializers named by their function. Heap size is only editable with the memory patch on; the save file field is a plain name.
- Mods: a profile changed outside the launcher (in a text editor, by me3 or an installer) is noticed. Coming back to the window reloads the Mods page, switches and Options act on the entry as it is in the file now rather than by its old position, and saving Edit profile over newer changes on disk asks first.
- Mods: an empty package folder says it is empty for now (game folders put there load), instead of reading as a problem.
- Mods: each DLL mod has a settings button that opens its own settings file (UnlockTheFps.ini, BetterCamera's ini, ...) in the editor, with Save and Discard and a .bak on save. Files beside the DLL are found on their own; one the mod reads under another name (SkeletonMan's skeleton_mods.txt) can be tied to it once and is remembered. Files keep their encoding and line endings. Seamless Co-op's settings stay on the Co-op page.
- Mods: the folder line's buttons sit on the right.
- Files: everything Roundtable Souls keeps now lives in its own data folder (%LOCALAPPDATA%\RoundtableSouls, or beside a portable copy): backups and the save library under saves\<game>\<Steam account>, deleted profiles under profiles\deleted, install unpacking under temp. Nothing of the launcher's is written into the game's save folder or me3's profile folders any more, apart from the offline .me3 copy and a single .bak beside an edited file. Folders earlier versions made there (save-fix-backups, regulation-fix-backups, co2-to-sl2-backups, sl2-to-co2-backups, roundtable-saves, deleted-profiles) are moved in automatically.
- Backups: named for what came next ("Before fixing checksums", "Before playing", "Before copying a character in"). The newest 20 of each save and everything from the last 7 days are kept; Keep holds on to one for good. The Backups card shows the total size. Copies between the co-op and standard save no longer keep a spare copy of the unchanged source.
- Fixed: expandable cards could keep empty space under their content, or cut off their last row after the list was refilled.
- Mods: drag one or more archives, DLLs or mod folders onto the Mods page to install them, one after another. The page shows what a drop would do while you drag, and names files it would skip.
- Mods: installing asks for the folder name and id, and shows what the mod holds with what to install: game files, the DLL and its settings are ticked; readmes, example .me3 profiles and other mod loaders' DLLs are not, each with the reason. Unrecognised files install as shipped. Files beside the mod's folder in the archive are listed too.
- Mods: the mod is found below wrapper folders and next to readmes, and an archive with several versions (an English and an Italian mod folder) asks which one. Text languages are named.
- Mods: a mod with a regulation.bin says that me3 uses only the last one in the load order and which package's is used now. It goes before that package by default (above the comment lines that describe its entry), or last, or without its regulation.bin.
- Mods: a lone .dll installs as a DLL mod. An archive that also ships an example .me3 installs as a mod instead of being refused as a profile.
- Fixed: after a job, the message and the Mods page refresh looked at how the job ended instead of what it was, so an install did not reload the page and every job reported "Saves repaired and cleanup done."

## [3.4.0] - 2026-09-28

- Games: a game button at the top of the window picks the game every page works on; its menu lists every game with whether it is installed, and Ctrl+Tab / Ctrl+Shift+Tab step through them. Elden Ring and Nightreign are supported; Dark Souls III and Sekiro have placeholder pages that only show what was found on the PC. Settings stays shared, and each game remembers its own setup and custom game exe.
- Nightreign: Play through me3 (online, or offline without Seamless Co-op), its me3 profiles and mods, and its Seamless Co-op settings (three difficulty values, no password in that mod). Saves are listed with a structure check, backups, restore, and copies between the co-op and standard save; Nightreign encrypts its saves, so characters are not shown.
- `--game <name>` picks the game for `--play` and `--check`, or the tab the window opens on for that run. Settings > Steam shortcut shows the launch options for the game on screen, one shortcut per game. An unknown name lists the valid ones.
- me3 profiles are listed under the game they name in `[[supports]]`; a profile that names none counts as Elden Ring's. Picking a profile made for another game says so instead of launching it.
- Setups: switching games no longer reads every profile's co-op settings up front, only the one in use. Two profiles with the same file name show their folder in the list, and the list is sorted by name.
- Fixed: deleting a profile on the Nightreign page cleared Elden Ring's remembered setup instead of Nightreign's.
- Fixed: a remembered setup written with different letter case or slashes was not found again, so Play could pick another one.

## [3.3.0] - 2026-09-27

- Saves: items the installed game defines always count as game items, read from the game's own regulation.bin. The Tarnished Edition pack's gear is recognised exactly, whether or not a character owns the pack; the guess based on the pack flag is only used when the game is not on this PC.
- Saves: mod items are named again. Seamless Co-op's items take their names from the mod's own language file, and other mods' items from the text files they ship (Windows, read with the game's own decompression library). Names are grouped by mod on the Saves page, and Review & fix can filter by mod when a save holds more than one.
- --check also writes its report to logs/last_run.log, adds the game data and mod names it found, and no longer shows the co-op password.
- Builds: tests run only when code, tests, build files or dependencies change, exactly as locked; a newer push cancels the older run. Releases must come from main, match the version, and are checked file by file before they go public. Changes to documentation alone skip the tests.

## [3.2.0] - 2026-09-27

- Licensing: the project is now GPL-3.0-or-later, matching the GPL-3.0 UI library the app is built on.
- Saves: items the game does not define are shown by kind and ID ("Armour 742000").
- Saves: Tarnished Edition and Shadow of the Erdtree are detected automatically, from the pack flag stored in the save and from DLC.bdt next to the game.
- Saves: Fix loading is a table of checks, each with its own repair.
- Saves: the weather check no longer runs; it flagged healthy characters during normal play.
- Layout: pages never scroll sideways. Page actions, status chips and button rows wrap; settings rows stack their control under the text; Review & fix turns its character list into a dropdown when the window is narrow. Checked at narrow widths and 150 % scaling.
- Names: Tools is now Settings; To .sl2 and To .co2 are Copy to standard save and Copy to co-op save; Worth knowing is Notes; one word, Refresh, for re-reading; folder buttons say which folder. The per-save Folder button is gone (the page has Saves folder).
- Buttons that are only an icon (delete, clear) are square with a tooltip; backups read as two lines per copy.
- Keyboard: nothing has focus when the window opens, so a stray Enter or Space cannot press Play. Ctrl+1 to Ctrl+5 open the pages, Esc leaves Review & fix, and focused buttons show a ring.
- Fixed: rebuilding the Saves page no longer trips a flood of internal layout errors.
- Fixed: copies made with Copy to co-op save appear in the Backups list.
- Installer: releases include RoundtableSouls-Setup.exe, a per-user install with no administrator prompt, a Start menu entry, an optional desktop shortcut and an uninstaller in Windows' app list. Installed copies keep settings in %LOCALAPPDATA%\RoundtableSouls, so updates and uninstalls never touch them. The portable zip stays available.
- Update now follows the install type: an installed copy downloads the new setup, checks it against SHA256SUMS.txt and runs it silently, which closes, updates and reopens the app; a portable copy swaps its exe as before. Settings shows which kind of copy is running.
- Linux and Steam Deck: a Linux build finds Steam (including Flatpak), the game, and the saves inside the game's Proton folder on any library or SD card; processes are read from /proc; me3's Linux paths are used; folders open with the desktop's handler.
- --play runs the Play session without the window, for a Steam shortcut, Big Picture or Steam Deck Gaming Mode. Settings > Steam shortcut shows the exact target and launch option to paste.
- The user guide and README were rewritten for this release.
- Tools: a Launcher card at the top holds the version, Check for updates, Releases and Logs, and the update toggle. The me3 card is back to me3 only, with one me3 folder button instead of two, me3 releases and Refresh.

## [3.1.4] - 2026-09-27

- Update now: the relaunch after an update crashed on its first start (the new exe inherited the old one's PyInstaller markers and looked for its files in a folder that was already gone; a manual start worked). The new exe is now started with a clean environment, detached from the old one.

## [3.1.3] - 2026-09-27

- Tools: the launcher update button is labelled Check for updates and sits before Launcher releases.

## [3.1.2] - 2026-09-27

- Tools > Check now asks GitHub for a newer launcher right away, ignoring the cache, and says Up to date when there is nothing. The automatic check now waits an hour between calls instead of a day.

## [3.1.1] - 2026-09-27

- Editors: Enter and Esc in the find bar no longer reach the document (Enter used to replace the found text with a line break). The bar keeps its colours after a theme switch and stays inside a narrow editor. Key-driven tests cover the bar.

## [3.1.0] - 2026-09-27

- Update now: the update notice can download the release, check it against the published SHA-256 checksums, swap the exe and restart. Still one click, never silent, and the manual Download link remains.
- Saves: To .co2 on a standard save makes the Seamless Co-op copy, backing up any existing .co2 first.
- Editors: Ctrl+F find and Ctrl+H replace with match case, regular expressions, Enter / Shift+Enter stepping and Replace all as one undo step.
- Releases now ship SHA256SUMS.txt next to the zip.

## [3.0.1] - 2026-09-27

- Tools > Check for launcher updates: once a day the launcher looks at this project's GitHub releases and shows a notice with a Download link when a newer version exists. Skip this version hides one release. Nothing is installed automatically.

## [3.0.0] - 2026-09-26

- Renamed to Roundtable Souls and rebuilt as a Python package (Python 3.14, uv). Settings are validated on load; the settings folder %LOCALAPPDATA%\Roundtable is carried over. No change to what the launcher does.

## [2.54]

- Characters last saved on an early game patch (slot version 81 or lower) now read. If a slot still cannot be read, the other characters show and that one is named and left alone.

## [2.53]

- Saves without Shadow of the Erdtree: DLC items are named as such and removable, with a Tools override for checking someone else's save.

## [2.52]

- Folder buttons: me3, Game and Saves under Tools > Folders, me3 folder on the me3 card, Saves folder on the Saves page, Profile folder on Mods, Game folder beside the setup picker. Each says why when a folder is unknown.

## [2.51]

- Less tied to one PC: Tools > Locations for a custom me3, game exe and profile folder; the profile folder follows me3 info; setups from an installation.json are labelled as such; the difficulty presets are named by party size; help texts name Seamless and the overhaul as examples, not assumptions.

## [2.50]

- Install mod accepts .7z and .rar as well as .zip.

## [2.49]

- Mods: install from a .zip or folder with package / DLL detection, per-mod options (loaded, optional, load early, initializer, finalizer, load order), remove with optional folder delete, on/off switches for every entry, new and delete profile.

## [2.48]

- Edge cases: profile settings keep a file without a final newline intact and never leave a duplicated key; a save file name must be a name, not a path; launch flags are skipped for a me3 older than 0.13; a setting change refuses to overwrite unsaved editor text; the me3 version follows the chosen setup.

## [2.47]

- Mods: package conflict scan, profile settings as menus, boot boost / logos / diagnostics launch flags, and the me3 version with an update notice and its logs.

## [2.46]

- Confirms read top to bottom: what will happen as bullets, then the safety line, then the button named for the action. Locks: with Elden Ring running, Apply, Restore and Undo stay off with the reason in their tooltip, and every write also waits for a save the game is still flushing.

## [2.45]

- Fix: the window opened on an empty Review & fix page instead of Play.

## [2.44]

- Altered versions of Tarnished Edition armour are recognised and named.

## [2.43]

- Tarnished Edition gear is official content: it counts as vanilla when the pack flag is on the save (Tools can override). Nothing worn is modded any more on such saves; the About card shows the pack pieces separately.

## [2.42]

- Review & fix: a page per save with characters on the left and every fix as a tick box on the right, search and filter for mod items, removals off by default, one Apply with Undo after. Backups list on the Saves page with Restore and Delete; every backup records what it was taken before. Tools > Play session toggles for backup before Play, process cleanup and repair. "Restore vanilla" is now "Remove mod items".

## [2.41]

- Restore vanilla, Fix quest flags and Fix loading open a checklist: pick characters, items and fixes one by one. Nothing is removed that you did not tick.

## [2.40]

- Fix loading: Torrent, position, DLC flags and weather repairs, with the usual confirm and backup. Torn writes are detected and named. Status chips on each save card; action buttons wrap on narrow windows.

## [2.39]

- Fix quest flags is always its own button when a soft-lock is found, next to Restore vanilla. Goods in a pouch slot no longer read as "worn".

## [2.38]

- Worth knowing shows one line per character with counts per mod; hover a line for the item names. The profile and share editors get Ctrl+/ comment toggle, Tab / Shift+Tab indent, Ctrl+D duplicate line.

## [2.37]

- Restore vanilla: strips Seamless and mod items by name, clears leftover rows and soft-locks, re-signs, backs up. The vanilla item list is rebuilt from the game's own item data, so vanilla goods, gestures and spirit-ash levels no longer read as unknown, and mod packs no longer pass as vanilla. Mod items are named on the Saves page.

## [2.36]

- Saves can fix quest soft-locks and stale checksums (asks first, backs up, re-signs). Item check understands weapon affinities and empty-slot placeholders; leftover entries from co-op partners' gear are informational only. The Saves icon shows a count only when a repair is available.

## [2.35]

- Saves panel spacing fits the content; notes are tighter and grouped.

## [2.34]

- Saves stay calm: characters first, optional "Worth knowing" notes only on that page. No Play banner for save checks.

## [2.33]

- Saves add duplicate-inventory, unknown item IDs, and known quest-flag soft-lock findings. Copy report and To .sl2 (only when clean). Play glances when a save needs attention.

## [2.32]

- Saves show regulation and layout findings, with Repair on a dirty block. Play warns when dead eldenring.exe shells are left behind and offers Clear.

## [2.31]

- The exe icon is a square plate with a size ladder (16–256). Windows 11 rounds it; 16 and 20 stay a ring and disc so they stay readable.

## [2.30]

- Everything is Roundtable. The mark is a circle with a transparent edge, like a current app icon.

## [2.29]

- The app is Roundtable. A grace mark replaces the old icon, and Tools can follow the theme or lock the logo to dark or light.

## [2.28]

- Gameplay settings are named menus and switches, not ini numbers. An info button explains each one. Offline play can skip the overhaul, skip starting Steam, and skip the confirm. The profile and share editors highlight TOML and JSON.

## [2.27]

- Launch log timestamps each line and colours errors. The profile and share boxes are code wells. Setup names the profile file, not this PC's folders.

## [2.26]

- Light is mid ice. Play is a deeper sea blue (#075C8B).

## [2.25]

- Light sits on a cooler frost ground. Play is a deeper sea blue.

## [2.24]

- Light is frost paper, a pale hero wash, and sea-blue Play.

## [2.23]

- Dark is the Lands Between gold strip. Light is Ranni frost and hatband dusk. Icon buttons keep a 36px slot so type does not sit under the glyph.

## [2.22]

- Ink canvas, antique gold only on Play and Save. The featured card holds the character, the Play action, and three facts. Pages paint their own ground so type stays readable.

## [2.21]

- The window shrinks to 720px. Play stacks the banner over the stats, difficulty goes to two columns, and padding tightens.

## [2.20]

- One glass palette: brighter violet, deeper background, 16px cards, 22px banner, pill Play and Save.

## [2.19]

- Design pass: quieter copy, Setup folded unless it is broken, Save profile on the Mods title when the file is dirty, Ctrl+S, and closing offers to save instead of only warning.

## [2.18]

- Co-op Save stays on a bar at the bottom of the page. It names what is unsaved and turns violet until you save or discard.

## [2.17]

- Windows 11 acrylic behind the window, and the featured card is translucent so the blur shows through. The setup line shows the program names; the full paths are on the tooltip.

## [2.16]

- Play is a featured card: the character and Play on the left, level, save, and body on the right.

## [2.14]

- Play leads with the character, then one Play button. Page titles are type only; the nav already carries the icon.

## [2.13]

- A profile that only has Seamless Co-op and the overhaul is read too, including the packages = [ ] form the overhaul's installer writes.

## [2.12]

- Panels ease open and shut, and a closed panel keeps only its header height.

## [2.11]

- Clearer layout. Refresh sits on the page title. Co-op hides its form when the setup has no Seamless. Launch log, and each save, fold. Closing asks if the profile or co-op settings are unsaved.

## [2.10]

- Mods lists only entries me3 will load (enabled is not false), with Refresh. Share, profile text, folders, offline play, and each save fold open and shut.

## [2.9]

- Mods page lists what is on and off, and edits the loaded me3 profile

## [2.8]

- Mods page: list packages and natives, turn them on or off

## [2.7]

- one Save co-op settings button for the password, difficulty, and the other options, with the unsaved list written above it

## [2.6]

- a confirmation when a setting is saved or applied; save buttons light up only when something changed

## [2.5]

- Nightreign-like presets for parties of 4, 5 and 6

## [2.4]

- offline play when Steam's login is down (solo, standard save)

## [2.3]

- Nightreign-like preset now uses Nightreign's real scaling rule

## [2.2]

- every Seamless Co-op setting editable in groups, your character on the Play page, status pills, one calm accent in dark and light

## [2.0]

- new window: Windows 11 Fluent look, pages (Play / Co-op / Saves / Tools), your character on the Play page, one Play button

## [1.7]

- safer file writes (.bak kept), error reporting, asks before closing while a session runs, settings fall back to LOCALAPPDATA

## [1.6]

- Share settings... : copy / paste / apply the settings as text

## [1.5]

- export / import settings as a .json file

## [1.4]

- difficulty scaling presets (Seamless default / Nightreign-like / Custom)

## [1.3]

- finds a the overhaul install inside the game folder by itself

## [1.2]

- saves panel, dark theme, no more terminal flashes

## [1.1]

- the overhaul setups, tools menu

## [1.0]

- first window version
