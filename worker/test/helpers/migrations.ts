import type { Database } from "../../src/db";

export interface MigrationFile {
  name: string;
  sql: string;
}

/** 주어진 마이그레이션 파일들을 파일명 순서대로 그대로 실행한다. */
export async function applyMigrations(db: Database, migrations: MigrationFile[]): Promise<void> {
  for (const migration of migrations) {
    await db.exec(migration.sql);
  }
}
