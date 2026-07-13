/** D1에 접근하는 Worker 모듈이 요구하는 데이터베이스 binding. */
export interface DatabaseBindings {
  DB: D1Database;
}

/** 저장소 모듈이 공유하는 D1 데이터베이스 타입. */
export type Database = DatabaseBindings["DB"];
