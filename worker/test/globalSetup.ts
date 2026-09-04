// D1 대신 각 테스트 파일이 격리된 로컬 Turso(libSQL) 서버를 쓰도록, 파일별로
// 고정 포트에 `turso dev`를 띄운다. 로컬에 turso CLI가 설치되어 있어야 한다
// (curl -sSfL https://get.tur.so/install.sh | bash).
import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

export const TEST_DATABASE_PORTS: Record<string, number> = {
  migrations: 8091,
  e2e: 8092,
  "public-api": 8093,
  retention: 8094,
  "admin-import": 8095,
};

async function waitForReady(port: number, timeoutMs = 20_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      await fetch(`http://127.0.0.1:${port}/`);
      return;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }
  throw new Error(`Local Turso dev server on port ${port} did not start in time.`);
}

export default async function setup(): Promise<() => Promise<void>> {
  const dir = await mkdtemp(path.join(tmpdir(), "radio-epg-turso-"));
  const processes: ChildProcess[] = [];

  for (const [name, port] of Object.entries(TEST_DATABASE_PORTS)) {
    const child = spawn(
      "turso",
      ["dev", "--db-file", path.join(dir, `${name}.db`), "--port", String(port)],
      { stdio: "ignore" },
    );
    child.on("error", (error: Error) => {
      throw new Error(
        `Failed to start "turso dev" (install it with curl -sSfL https://get.tur.so/install.sh | bash): ${error.message}`,
      );
    });
    processes.push(child);
  }

  await Promise.all(Object.values(TEST_DATABASE_PORTS).map((port) => waitForReady(port)));

  return async () => {
    for (const child of processes) {
      child.kill();
    }
    await rm(dir, { recursive: true, force: true });
  };
}
