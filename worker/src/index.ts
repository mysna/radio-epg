import { Hono } from "hono";

import { errorResponse } from "./errors";
import retention from "./retention";
import adminImport from "./routes/admin-import";
import channels from "./routes/channels";
import coverage from "./routes/coverage";
import nowRoute from "./routes/now";
import schedules from "./routes/schedules";
import type { AppEnv } from "./types";

const app = new Hono<AppEnv>();

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
