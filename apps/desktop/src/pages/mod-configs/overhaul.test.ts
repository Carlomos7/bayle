import { describe, expect, test } from "vitest";
import { decodeAction, encodeAction, formOf, patchValues, shownValue } from "./overhaul";
import type { FormValues } from "./types";

const values = (): FormValues => ({
  natives: [{ file: "A.dll", load_early: false, after_others: false, initializer: null }],
  files: { "x.bin": "merge", "y.bin": "place:old/y.bin" },
  tables: { "menu.msgbnd": "" },
  health: { log: "", fail: "", ok: "" },
});

describe("the setup form's edits", () => {
  test("actions encode and decode as the backend stores them", () => {
    expect(encodeAction("place", "a/b")).toBe("place:a/b");
    expect(encodeAction("merge", "a/b")).toBe("merge");
    expect(decodeAction("place:a/b")).toEqual(["place", "a/b"]);
    expect(decodeAction("skip")).toEqual(["skip", ""]);
  });

  test("a DLL's options and initializer", () => {
    let v = patchValues(values(), "early:A.dll", "true");
    v = patchValues(v, "after:A.dll", "true");
    v = patchValues(v, "init:A.dll", "  Boot ");
    expect(v.natives[0]).toMatchObject({ load_early: true, after_others: true, initializer: "Boot" });
    expect(patchValues(v, "init:A.dll", "  ").natives[0]!.initializer).toBeNull();
    expect(shownValue(v, "init:A.dll", "")).toBe("Boot");
  });

  test("placing a file keeps the path typed before, and the path edit places it", () => {
    const v = patchValues(values(), "file:y.bin", "merge");
    expect(v.files["y.bin"]).toBe("merge");
    expect(patchValues(v, "file:y.bin", "place").files["y.bin"]).toBe("place:");
    expect(patchValues(values(), "file:y.bin", "place").files["y.bin"]).toBe("place:old/y.bin");
    expect(patchValues(values(), "target:x.bin", " mod/x.bin ").files["x.bin"]).toBe("place:mod/x.bin");
    expect(shownValue(values(), "target:y.bin", "")).toBe("old/y.bin");
    expect(shownValue(values(), "file:y.bin", "")).toBe("place");
  });

  test("the log check is only sent once it was touched", () => {
    expect(formOf(values()).health).toBeNull();
    const v = patchValues(values(), "health:log", "log.txt");
    expect(formOf(v).health).toEqual({ log: "log.txt", fail: "", ok: "" });
  });

  test("a key that names nothing changes nothing", () => {
    const v = values();
    expect(patchValues(v, "early:Missing.dll", "true")).toBe(v);
    expect(patchValues(v, "health:nope", "x")).toBe(v);
    expect(patchValues(v, "bogus:thing", "x")).toBe(v);
  });
});
