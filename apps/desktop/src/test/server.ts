import { setupServer } from "msw/node";

export const BASE = "http://127.0.0.1:5";
export const backend = { base_url: BASE, token: "t", app_version: "9", contract_version: "1" };
export const server = setupServer();
