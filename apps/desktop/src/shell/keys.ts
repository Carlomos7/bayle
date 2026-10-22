/** Global keys, as the Qt window has them (Main.qml and views/menu.py). Returns the action id or undefined. */
export function actionForKey(e: Pick<KeyboardEvent, "key" | "ctrlKey" | "shiftKey" | "altKey" | "metaKey">): string | undefined {
  if (e.altKey || e.metaKey) return undefined;
  if (e.key === "F1" && !e.ctrlKey && !e.shiftKey) return "help.how";
  if (!e.ctrlKey) return undefined;
  const k = e.key.toLowerCase();
  if (e.key === "Tab") return e.shiftKey ? "game.prev" : "game.next";
  if (k === "l") return e.shiftKey ? "launch.menu" : "launch";
  if (e.shiftKey) return undefined;
  if (k === "n") return "file.new";
  if (k === "q") return "file.exit";
  const page = ["view.mods", "view.configs", "view.saves", "view.activity", "view.settings"][Number(e.key) - 1];
  return page;
}
