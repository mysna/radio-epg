import { Hono } from "hono";

import { cachedJson, errorResponse } from "../errors";
import { listChannels, resolveChannel } from "../repositories/channels";
import type { AppEnv } from "../types";

const channels = new Hono<AppEnv>();

channels.get("/", async (context) => {
  const result = await listChannels(context.env.DB);
  return cachedJson(context, { channels: result }, "public, max-age=3600");
});

channels.get("/:identifier", async (context) => {
  const channel = await resolveChannel(context.env.DB, context.req.param("identifier"));
  if (!channel) {
    return errorResponse(
      context,
      404,
      "channel_not_found",
      "The requested channel alias is not registered.",
    );
  }
  return cachedJson(context, channel, "public, max-age=3600");
});

export default channels;
