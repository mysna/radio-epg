import { createClient, type Client, type InStatement, type InValue } from "@libsql/client";

/** D1과 동일한 모양으로 맞춘 실행 결과. run()/batch()가 반환한다. */
export interface DatabaseRunResult {
  meta: { changes: number; last_row_id?: bigint };
}

/** D1과 동일한 모양으로 맞춘 조회 결과. all()이 반환한다. */
export interface DatabaseResult<T> {
  results: T[];
}

/** D1PreparedStatement와 동일한 사용법(prepare().bind().all()/.first()/.run())을 제공한다. */
export interface DatabaseStatement {
  bind(...args: InValue[]): DatabaseStatement;
  all<T = unknown>(): Promise<DatabaseResult<T>>;
  first<T = unknown>(): Promise<T | null>;
  run(): Promise<DatabaseRunResult>;
}

/** Turso(libSQL) 기반 데이터베이스. 기존 D1 호출부를 그대로 재사용할 수 있는 형태다. */
export interface Database {
  prepare(sql: string): DatabaseStatement;
  batch(statements: DatabaseStatement[]): Promise<DatabaseRunResult[]>;
  /** 세미콜론으로 구분된 마이그레이션 SQL 스크립트를 그대로 실행한다. */
  exec(sql: string): Promise<void>;
}

class LibsqlStatement implements DatabaseStatement {
  constructor(
    private readonly client: Client,
    private readonly sql: string,
    private readonly args: InValue[] = [],
  ) {}

  bind(...args: InValue[]): LibsqlStatement {
    return new LibsqlStatement(this.client, this.sql, args);
  }

  toInStatement(): InStatement {
    return { sql: this.sql, args: this.args };
  }

  async all<T>(): Promise<DatabaseResult<T>> {
    const result = await this.client.execute(this.toInStatement());
    return { results: result.rows as unknown as T[] };
  }

  async first<T>(): Promise<T | null> {
    const result = await this.client.execute(this.toInStatement());
    return (result.rows[0] as unknown as T) ?? null;
  }

  async run(): Promise<DatabaseRunResult> {
    const result = await this.client.execute(this.toInStatement());
    return { meta: { changes: result.rowsAffected, last_row_id: result.lastInsertRowid } };
  }
}

class LibsqlDatabase implements Database {
  constructor(private readonly client: Client) {}

  prepare(sql: string): DatabaseStatement {
    return new LibsqlStatement(this.client, sql);
  }

  async batch(statements: DatabaseStatement[]): Promise<DatabaseRunResult[]> {
    const inStatements = statements.map((statement) => {
      if (!(statement instanceof LibsqlStatement)) {
        throw new TypeError("batch() only accepts statements created by this database's prepare()");
      }
      return statement.toInStatement();
    });
    // D1의 batch()처럼 전부 성공하거나 전부 롤백되도록 write 트랜잭션으로 묶는다.
    const results = await this.client.batch(inStatements, "write");
    return results.map((result) => ({
      meta: { changes: result.rowsAffected, last_row_id: result.lastInsertRowid },
    }));
  }

  async exec(sql: string): Promise<void> {
    await this.client.executeMultiple(sql);
  }
}

/** Worker가 요구하는 데이터베이스 binding. 실제 값은 미들웨어가 채운다. */
export interface DatabaseBindings {
  DB?: Database;
}

/** Turso 접속 정보로 Database를 만든다. */
export function createDatabase(config: { url: string; authToken?: string }): Database {
  return new LibsqlDatabase(createClient(config));
}
