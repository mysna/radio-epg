import { Hono } from "hono";

import { edgeCache, matchChannelCache, putChannelCache } from "../cache";
import type { Database } from "../db";
import { cachedJson, errorResponse } from "../errors";
import { resolveChannelIds } from "../repositories/channels";
import { currentAndNextForChannels, type CurrentAndNext } from "../repositories/schedules";
import type { AppEnv } from "../types";

const nowRoute = new Hono<AppEnv>();
const CACHE_NAMESPACE = "now/channel";
const MIN_CACHE_AGE_SECONDS = 30;
const MAX_CACHE_AGE_SECONDS = 300;
/**
 * 채널마다 cache.match/put을 하나씩 날리면 채널 수만큼 subrequest가 생긴다.
 * Cloudflare Workers는 요청 하나당 subrequest 수에 상한이 있어서, 즐겨찾기를
 * 전체 채널처럼 많이 선택한 요청은 이 한도를 넘겨 500으로 죽는다. 그 상한보다
 * 넉넉히 낮은 채널 수부터는 채널별 캐시를 건너뛰고 DB를 한 번에 배치 조회한다.
 */
const PER_CHANNEL_CACHE_LIMIT = 30;

/**
 * 캐시 수명을 현재 편성이 끝나는 시각까지로 잡는다. 고정 30초로 캐시하면 한
 * 시간짜리 프로그램 하나를 보여주려고 같은 채널을 120번 다시 조회하지만,
 * 경계까지 유지하면 값이 실제로 바뀌는 시점에만 DB를 읽는다.
 */
function cacheAgeSeconds(schedule: CurrentAndNext, now: Date): number {
  const boundary = schedule.current?.ends_at ?? schedule.next?.starts_at;
  if (!boundary) {
    return MAX_CACHE_AGE_SECONDS;
  }
  const remaining = Math.floor((new Date(boundary).getTime() - now.getTime()) / 1000);
  return Math.min(MAX_CACHE_AGE_SECONDS, Math.max(MIN_CACHE_AGE_SECONDS, remaining));
}

/**
 * 채널별로 캐시를 조회하고, 미스인 채널만 한 번의 DB 질의로 채운다. 사용자마다
 * 다른 재생목록 조합을 요청 단위로 캐시하면 조합이 거의 겹치지 않아 캐시가
 * 무의미해지므로, channel_id 단위로 캐시해 조합과 무관하게 재사용한다.
 */
async function currentAndNextCached(
  database: Database,
  channelIds: string[],
  now: Date,
): Promise<Map<string, CurrentAndNext>> {
  if (channelIds.length > PER_CHANNEL_CACHE_LIMIT) {
    const fresh = await currentAndNextForChannels(database, channelIds, now);
    return new Map(
      channelIds.map((channelId) => [channelId, fresh.get(channelId) ?? { current: null, next: null }]),
    );
  }

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
        await putChannelCache(
          cache,
          CACHE_NAMESPACE,
          channelId,
          schedule,
          cacheAgeSeconds(schedule, now),
        );
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
  const db = context.get("db");
  // 식별자 해석과 편성 조회를 각각 한 번씩만 수행한다.
  const channelIds = await resolveChannelIds(db, radioIds);
  const schedules = await currentAndNextCached(
    db,
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

  // 응답 수명은 가장 먼저 바뀌는 채널에 맞춘다.
  const maxAgeSeconds = [...schedules.values()].reduce(
    (shortest, schedule) => Math.min(shortest, cacheAgeSeconds(schedule, requestedAt)),
    MAX_CACHE_AGE_SECONDS,
  );

  return cachedJson(
    context,
    { requested_at: requestedAt.toISOString(), results },
    `public, max-age=${maxAgeSeconds}`,
  );
});

export default nowRoute;
