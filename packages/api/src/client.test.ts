import { expect, test, vi } from "vitest";
import { createClient } from ".";

test("health goes to the base url with the bearer token", async () => {
  const body = { app_version: "1", contract_version: "1", ready: true };
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } }));
  const api = createClient({ baseUrl: "http://h", token: "t" });
  api.client.setConfig({ fetch });
  expect(await api.health()).toEqual(body);
  const req = fetch.mock.calls[0]![0] as Request;
  expect(req.url).toBe("http://h/v1/health");
  expect(req.headers.get("Authorization")).toBe("Bearer t");
});
