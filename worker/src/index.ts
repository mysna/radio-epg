import { Hono } from "hono";

import { createDatabase } from "./db";
import { errorResponse } from "./errors";
import retention from "./retention";
import adminImport from "./routes/admin-import";
import channels from "./routes/channels";
import coverage from "./routes/coverage";
import nowRoute from "./routes/now";
import schedules from "./routes/schedules";
import type { AppEnv } from "./types";

const app = new Hono<AppEnv>();

// 테스트는 바인딩으로 Database를 직접 주입하고, 배포 환경은 여기서 Turso 접속 정보로
// 한 번만 만들어 재사용한다. /health처럼 DB가 필요 없는 라우트는 바인딩이 없어도 통과한다.
app.use("*", async (context, next) => {
  const bindings = context.env ?? {};
  const db =
    bindings.DB ?? (bindings.TURSO_DATABASE_URL
      ? createDatabase({ url: bindings.TURSO_DATABASE_URL, authToken: bindings.TURSO_AUTH_TOKEN })
      : undefined);
  if (db) {
    context.set("db", db);
  }
  await next();
});

app.use("/v1/*", async (context, next) => {
  const origin = context.req.header("Origin");
  if (!origin) {
    await next();
    context.header("Vary", "Origin", { append: true });
    return;
  }

  const allowedOrigins = (context.env.CORS_ORIGINS ?? "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  if (!allowedOrigins.includes(origin)) {
    return errorResponse(
      context,
      403,
      "origin_not_allowed",
      "The request origin is not allowed.",
    );
  }

  if (context.req.method === "OPTIONS") {
    return context.newResponse(null, 204, {
      "Access-Control-Allow-Headers": "Content-Type, If-None-Match",
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Access-Control-Allow-Origin": origin,
      Vary: "Origin",
    });
  }

  await next();
  context.header("Access-Control-Allow-Origin", origin);
  context.header("Vary", "Origin", { append: true });
});

app.get("/health", (context) => context.json({ service: "radio-epg" }));
app.route("/v1/channels", channels);
app.route("/v1/schedules", schedules);
app.route("/v1/now", nowRoute);
app.route("/v1/coverage", coverage);
app.route("/v1/admin/import", adminImport);
app.route("/v1/admin/retention", retention);

export default app;
