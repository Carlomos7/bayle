import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { CodeEditor, languageFor } from "./CodeEditor";

describe("CodeEditor", () => {
  test("picks the language by the file's extension", () => {
    expect(languageFor("a.me3")).toBe("toml");
    expect(languageFor("C:/x/Settings.INI")).toBe("ini");
    expect(languageFor("a.hks")).toBe("lua");
    expect(languageFor("a.bin")).toBe("");
  });

  test("shows the text with line numbers and the cursor position", async () => {
    render(<CodeEditor value={"a = 1\nb = 2\n"} fileName="x.toml" aria-label="the file" />);
    const box = await screen.findByRole("textbox", { name: "the file" });
    expect(box).toHaveTextContent("a = 1");
    expect(document.querySelector(".cm-lineNumbers")).not.toBeNull();
    expect(screen.getByText("Line 1, column 1")).toBeInTheDocument();
  });

  test("marks the error the check finds and says it under the editor", async () => {
    const check = vi.fn().mockResolvedValue({ line: 2, message: "Line 2: a key is missing its value" });
    render(<CodeEditor value={"a = 1\nb =\n"} fileName="x.toml" check={check} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Line 2: a key is missing its value");
    expect(check).toHaveBeenCalledWith("a = 1\nb =\n");
    await waitFor(() => expect(document.querySelector(".cm-lintRange-error")).not.toBeNull());
  });

  test("a new value from outside replaces the document", async () => {
    const { rerender } = render(<CodeEditor value="one" fileName="x.txt" aria-label="f" />);
    rerender(<CodeEditor value="two" fileName="x.txt" aria-label="f" />);
    await waitFor(() => expect(screen.getByRole("textbox", { name: "f" })).toHaveTextContent("two"));
  });
});
