import { Hono } from "hono";

const app = new Hono();

app.get("/health", (context) => context.json({ service: "radio-epg" }));

export default app;
