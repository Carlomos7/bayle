import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: "../../docs/api/openapi.json",
  output: { path: "src/generated" },
  plugins: ["@hey-api/client-fetch", "@hey-api/typescript", "@hey-api/sdk"],
});
