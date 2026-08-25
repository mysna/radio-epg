import { Hono } from "hono";

import { edgeCachedJson } from "../cache";
import { errorResponse } from "../errors";
import { resolveChannelIds } from "../repositories/channels";
import { currentAndNextForChannels } from "../repositories/schedules";
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

  return edgeCachedJson(context, "public, max-age=30", async () => {
    const requestedAt = new Date();
    // 식별자 해석과 편성 조회를 각각 한 번씩만 수행한다.
    const channelIds = await resolveChannelIds(context.env.DB, radioIds);
    const schedules = await currentAndNextForChannels(
      context.env.DB,
      [...new Set(channelIds.values())],
      requestedAt,
    );

    const results = radioIds.map((radioId) => {
      const channelId = channelIds.get(radioId);
      if (!channelId) {
        return {
          radio_id: radioId,
          channel_id: null,
          status: "not_found",
          current: null,
          next: null,
        };
      }
      const schedule = schedules.get(channelId) ?? { current: null, next: null };
      return {
        radio_id: radioId,
        channel_id: channelId,
        status: schedule.current || schedule.next ? "available" : "unavailable",
        ...schedule,
      };
    });

    return { requested_at: requestedAt.toISOString(), results };
  });
});

export default nowRoute;
