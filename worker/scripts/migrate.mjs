#!/usr/bin/env node
// Turso(libSQL)에 worker/migrations/*.sql을 순서대로, 아직 적용되지 않은 것만 적용한다.
// wrangler의 `d1 migrations apply`를 대체한다. 사용법:
//   TURSO_DATABASE_URL=... TURSO_AUTH_TOKEN=... node scripts/migrate.mjs
import { createClient } from "@libsql/client";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const workerDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const migrationsDir = path.join(workerDir, "migrations");

const url = process.env.TURSO_DATABASE_URL;
const authToken = process.env.TURSO_AUTH_TOKEN;
if (!url) {
  console.error("TURSO_DATABASE_URL is required.");
  process.exit(1);
}

const client = createClient({ url, authToken });

async function main() {
  await client.execute(
    "CREATE TABLE IF NOT EXISTS _migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
  );
  const applied = new Set(
    (await client.execute("SELECT name FROM _migrations")).rows.map((row) => String(row.name)),
  );

  const files = (await readdir(migrationsDir)).filter((name) => name.endsWith(".sql")).sort();
  for (const file of files) {
    if (applied.has(file)) {
      continue;
    }
    const sql = await readFile(path.join(migrationsDir, file), "utf8");
    console.log(`Applying ${file}...`);
    await client.executeMultiple(sql);
    await client.execute({ sql: "INSERT INTO _migrations (name) VALUES (?)", args: [file] });
  }
  console.log("Migrations up to date.");
}

main()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  .finally(() => client.close());
