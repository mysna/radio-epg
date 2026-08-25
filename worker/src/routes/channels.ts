import { Hono } from "hono";

import { edgeCachedJson } from "../cache";
import { errorResponse } from "../errors";
import { listChannels, resolveChannel } from "../repositories/channels";
import type { AppEnv } from "../types";

const channels = new Hono<AppEnv>();

channels.get("/", async (context) =>
  edgeCachedJson(context, "public, max-age=3600", async () => ({
    channels: await listChannels(context.env.DB),
  })),
);

channels.get("/:identifier", async (context) =>
  edgeCachedJson(context, "public, max-age=3600", async () => {
    const channel = await resolveChannel(context.env.DB, context.req.param("identifier"));
    if (!channel) {
      return errorResponse(
        context,
        404,
        "channel_not_found",
        "The requested channel alias is not registered.",
      );
    }
    return channel;
  }),
);

export default channels;
