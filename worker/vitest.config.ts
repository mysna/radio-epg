import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { defineConfig } from "vitest/config";

async function readMigrations(dir: string): Promise<{ name: string; sql: string }[]> {
  const files = (await readdir(dir)).filter((name) => name.endsWith(".sql")).sort();
  return Promise.all(
    files.map(async (name) => ({ name, sql: await readFile(path.join(dir, name), "utf8") })),
  );
}

export default defineConfig({
  test: {
    globalSetup: ["./test/globalSetup.ts"],
  },
  plugins: [
    cloudflareTest(async () => {
      const migrations = await readMigrations(new URL("./migrations", import.meta.url).pathname);

      return {
        wrangler: { configPath: "./wrangler.toml" },
        miniflare: {
          bindings: { TEST_MIGRATIONS: migrations },
        },
      };
    }),
  ],
});
