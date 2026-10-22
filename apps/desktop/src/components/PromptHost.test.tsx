import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, test, vi } from "vitest";
import { BackendProvider } from "@/api/backend";
import type { PlanOffer, PromptWords } from "@/api/types";
import { backend, BASE, server } from "@/test/server";
import { PromptHost, usePrompts } from "./PromptHost";
import type { Toasts } from "./toasts";

const toasts = { error: vi.fn() } as unknown as Toasts;

/** Capture every POST to the backend's answer routes. */
function recordAnswers() {
  const posted: { path: string; body: unknown }[] = [];
  server.use(
    http.post(`${BASE}/v1/plans/:id`, async ({ request, params }) => {
      posted.push({ path: `/v1/plans/${String(params.id)}`, body: await request.json() });
      return HttpResponse.json({ job_id: null });
    }),
    http.post(`${BASE}/v1/prompts/:id`, async ({ request, params }) => {
      posted.push({ path: `/v1/prompts/${String(params.id)}`, body: await request.json() });
      return HttpResponse.json({ ok: true });
    }),
  );
  return posted;
}

function Opener({ offer, prompt }: { offer?: PlanOffer; prompt?: PromptWords & { prompt_id: string } }) {
  const { offerPlan, askPrompt } = usePrompts();
  return <button onClick={() => (offer ? offerPlan(offer) : askPrompt(prompt!))}>open</button>;
}

async function open(props: Parameters<typeof Opener>[0]) {
  const user = userEvent.setup();
  render(
    <BackendProvider backend={backend}>
      <PromptHost toasts={toasts}>
        <Opener {...props} />
      </PromptHost>
    </BackendProvider>,
  );
  await user.click(screen.getByText("open"));
  return user;
}

describe("PromptHost", () => {
  test("confirm lists the changes, focuses Cancel first and posts the apply answer with the option", async () => {
    const posted = recordAnswers();
    const user = await open({
      offer: {
        plan_id: "p1",
        prompt: {
          kind: "confirm",
          title: "Install Foo?",
          changes: ["Copy 3 files", "Add it to the profile"],
          apply: "Install",
          warning: "Replaces Foo 1.0",
          option: "Keep a backup",
          option_checked: false,
        },
      },
    });
    expect(screen.getByRole("alertdialog", { name: "Install Foo?" })).toBeInTheDocument();
    expect(screen.getByText("Copy 3 files")).toBeInTheDocument();
    expect(screen.getByText("Replaces Foo 1.0")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();

    await user.click(screen.getByRole("checkbox", { name: "Keep a backup" }));
    await user.click(screen.getByRole("button", { name: "Install" }));

    await vi.waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toEqual({ path: "/v1/plans/p1", body: { ok: true, option: true, choice: "", ticked: [] } });
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  test("pick posts the ticked rows and blocks Apply while none is ticked", async () => {
    const posted = recordAnswers();
    const user = await open({
      offer: {
        plan_id: "p2",
        prompt: { kind: "pick", title: "Move to the Recycle Bin", body: "Leftovers:", apply: "Move", rows: ["a.dll", "b.dll", "c.dll"], ticked: [1] },
      },
    });
    expect(screen.getByRole("checkbox", { name: "b.dll" })).toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "b.dll" }));
    expect(screen.getByRole("button", { name: "Move" })).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: "c.dll" }));
    await user.click(screen.getByRole("checkbox", { name: "a.dll" }));
    await user.click(screen.getByRole("button", { name: "Move" }));

    await vi.waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toEqual({ path: "/v1/plans/p2", body: { ok: true, option: false, choice: "", ticked: [0, 2] } });
  });

  test("choose (a prompt event) posts the chosen key to /v1/prompts", async () => {
    const posted = recordAnswers();
    const user = await open({
      prompt: {
        prompt_id: "q7",
        kind: "choose",
        title: "Steam is not running",
        lines: ["Start it first?"],
        choices: [
          { key: "start", label: "Start Steam", role: "primary" },
          { key: "cancel", label: "Cancel" },
        ],
      },
    });
    await user.click(screen.getByRole("button", { name: "Start Steam" }));
    await vi.waitFor(() => expect(posted).toEqual([{ path: "/v1/prompts/q7", body: { choice: "start" } }]));
  });

  test("Escape on a prompt event answers with the cancel key so the job is released", async () => {
    const posted = recordAnswers();
    const user = await open({
      prompt: {
        prompt_id: "q8",
        kind: "choose",
        title: "Which way?",
        lines: [],
        choices: [
          { key: "a", label: "A" },
          { key: "cancel", label: "Cancel" },
        ],
      },
    });
    await user.keyboard("{Escape}");
    await vi.waitFor(() => expect(posted).toEqual([{ path: "/v1/prompts/q8", body: { choice: "cancel" } }]));
  });

  test("cancelling a plan posts nothing", async () => {
    const posted = recordAnswers();
    const user = await open({
      offer: { plan_id: "p3", prompt: { kind: "confirm", title: "Delete?", changes: [], apply: "Delete" } },
    });
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(posted).toEqual([]);
  });

  test("refusal is told with a Close button and posts nothing", async () => {
    const posted = recordAnswers();
    const user = await open({
      offer: { plan_id: null, prompt: { kind: "refusal", title: "Cannot do that", body: "The game is running." } },
    });
    expect(screen.getByText("The game is running.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(posted).toEqual([]);
  });

  test("keeps focus inside the dialog when tabbing", async () => {
    recordAnswers();
    const user = await open({
      offer: { plan_id: "p4", prompt: { kind: "confirm", title: "Sure?", changes: [], apply: "Do it" } },
    });
    for (let i = 0; i < 5; i++) {
      await user.tab();
      expect(screen.getByRole("alertdialog")).toContainElement(document.activeElement as HTMLElement);
    }
  });

  test("a failed answer shows the error toast", async () => {
    server.use(
      http.post(`${BASE}/v1/plans/:id`, () =>
        HttpResponse.json({ code: "plan_expired", message: "That offer ran out.", details: {} }, { status: 410 }),
      ),
    );
    const user = await open({
      offer: { plan_id: "p5", prompt: { kind: "confirm", title: "Sure?", changes: [], apply: "Go" } },
    });
    await user.click(screen.getByRole("button", { name: "Go" }));
    await vi.waitFor(() => expect(toasts.error).toHaveBeenCalled());
  });
});
