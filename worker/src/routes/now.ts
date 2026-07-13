import { Hono } from "hono";

import { cachedJson, errorResponse } from "../errors";
import { resolveChannel } from "../repositories/channels";
import { currentAndNext } from "../repositories/schedules";
import type { AppEnv } from "../types";

const nowRoute = new Hono<AppEnv>();

nowRoute.get("/", async (context) => {
  const radioIds = (context.req.query("radio_ids") ?? "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  if (radioIds.length === 0) {
    return errorResponse(context, 400, "missing_radio_ids", "radio_ids is required.");
  }
  if (radioIds.length > 100) {
    return errorResponse(
      context,
      400,
      "too_many_radio_ids",
      "radio_ids must contain at most 100 values.",
    );
  }

  const requestedAt = new Date();
  const results = [];
  for (const radioId of radioIds) {
    const channel = await resolveChannel(context.env.DB, radioId);
    if (!channel) {
      return errorResponse(
        context,
        404,
        "channel_not_found",
        "The requested channel alias is not registered.",
      );
    }
    const schedule = await currentAndNext(context.env.DB, channel.channel_id, requestedAt);
    results.push({
      radio_id: radioId,
      channel_id: channel.channel_id,
      status: schedule.current || schedule.next ? "available" : "unavailable",
      ...schedule,
    });
  }

  return cachedJson(
    context,
    { requested_at: requestedAt.toISOString(), results },
    "public, max-age=30",
  );
});

export default nowRoute;
