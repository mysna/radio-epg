import { Hono } from "hono";

import { edgeCache, matchChannelCache, putChannelCache } from "../cache";
import { cachedJson, errorResponse } from "../errors";
import { resolveChannelIds } from "../repositories/channels";
import { currentAndNextForChannels, type CurrentAndNext } from "../repositories/schedules";
import type { AppEnv } from "../types";

const nowRoute = new Hono<AppEnv>();
const CACHE_NAMESPACE = "now/channel";
const CACHE_MAX_AGE_SECONDS = 30;

/**
 * 채널별로 캐시를 조회하고, 미스인 채널만 한 번의 D1 질의로 채운다. 사용자마다
 * 다른 재생목록 조합을 요청 단위로 캐시하면 조합이 거의 겹치지 않아 캐시가
 * 무의미해지므로, channel_id 단위로 캐시해 조합과 무관하게 재사용한다.
 */
async function currentAndNextCached(
  database: AppEnv["Bindings"]["DB"],
  channelIds: string[],
  now: Date,
): Promise<Map<string, CurrentAndNext>> {
  const cache = edgeCache();
  const schedules = new Map<string, CurrentAndNext>();
  const misses: string[] = [];

  await Promise.all(
    channelIds.map(async (channelId) => {
      const cached = await matchChannelCache<CurrentAndNext>(cache, CACHE_NAMESPACE, channelId);
      if (cached) {
        schedules.set(channelId, cached);
      } else {
        misses.push(channelId);
      }
    }),
  );

  if (misses.length > 0) {
    const fresh = await currentAndNextForChannels(database, misses, now);
    await Promise.all(
      misses.map(async (channelId) => {
        const schedule = fresh.get(channelId) ?? { current: null, next: null };
        schedules.set(channelId, schedule);
        await putChannelCache(cache, CACHE_NAMESPACE, channelId, schedule, CACHE_MAX_AGE_SECONDS);
      }),
    );
  }

  return schedules;
}

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
  // 식별자 해석과 편성 조회를 각각 한 번씩만 수행한다.
  const channelIds = await resolveChannelIds(context.env.DB, radioIds);
  const schedules = await currentAndNextCached(
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

  return cachedJson(
    context,
    { requested_at: requestedAt.toISOString(), results },
    `public, max-age=${CACHE_MAX_AGE_SECONDS}`,
  );
});

export default nowRoute;
