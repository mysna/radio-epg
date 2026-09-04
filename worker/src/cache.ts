import type { Context } from "hono";

import { cachedJson } from "./errors";
import type { AppEnv } from "./types";

/** WebWorker lib의 CacheStorage 타입에는 없는 Cloudflare 기본 캐시를 가져온다. */
export function edgeCache(): Cache {
  return (caches as unknown as { default: Cache }).default;
}

/**
 * 채널 하나의 값을 edge cache에서 읽는다. 요청 조합(radio_ids)이 아니라
 * channel_id를 키로 쓰므로, 사용자마다 다른 재생목록 조합이어도 겹치는
 * 채널은 캐시를 공유해 DB 조회를 피한다.
 */
export async function matchChannelCache<T>(
  cache: Cache,
  cacheNamespace: string,
  channelId: string,
): Promise<T | null> {
  const hit = await cache.match(`https://edge-cache.internal/${cacheNamespace}/${channelId}`);
  if (!hit) {
    return null;
  }
  return (await hit.json()) as T;
}

/** 채널 하나의 값을 edge cache에 지정한 max-age만큼 저장한다. */
export async function putChannelCache(
  cache: Cache,
  cacheNamespace: string,
  channelId: string,
  value: unknown,
  maxAgeSeconds: number,
): Promise<void> {
  const response = new Response(JSON.stringify(value), {
    headers: {
      "Cache-Control": `public, max-age=${maxAgeSeconds}`,
      "Content-Type": "application/json",
    },
  });
  await cache.put(`https://edge-cache.internal/${cacheNamespace}/${channelId}`, response);
}

/** 질의 문자열 순서가 달라도 같은 항목을 쓰도록 캐시 키를 정규화한다. */
function cacheKey(requestUrl: string): Request {
  const url = new URL(requestUrl);
  const parameters = [...url.searchParams.entries()].sort(([left], [right]) =>
    left < right ? -1 : left > right ? 1 : 0,
  );
  url.search = new URLSearchParams(parameters).toString();
  return new Request(url.toString(), { method: "GET" });
}

/** 캐시에서 꺼낸 응답을 헤더 수정이 가능한 사본으로 되돌린다. */
function replayable(response: Response): Response {
  return new Response(response.body, {
    status: response.status,
    headers: new Headers(response.headers),
  });
}

function notModified(response: Response, ifNoneMatch: string | undefined): Response | null {
  const etag = response.headers.get("ETag");
  if (!etag || ifNoneMatch !== etag) {
    return null;
  }
  return new Response(null, { status: 304, headers: new Headers(response.headers) });
}

/**
 * 공개 읽기 응답을 Cloudflare edge cache에 담는다. build가 Response를 반환하면
 * 오류 응답으로 보고 캐시하지 않는다. cacheControl이 함수이면 build 결과를 보고
 * 정책을 정한다 — 막 배포되었거나 수집 중이라 결과가 비어 있는 응답을 일반
 * TTL로 캐싱하면, 뒤이어 데이터가 채워져도 그 TTL이 끝날 때까지 edge가 빈
 * 응답을 계속 돌려준다.
 */
export async function edgeCachedJson(
  context: Context<AppEnv>,
  cacheControl: string | ((built: unknown) => string),
  build: () => Promise<unknown>,
): Promise<Response> {
  const cache = edgeCache();
  const key = cacheKey(context.req.url);
  const ifNoneMatch = context.req.header("If-None-Match");

  const hit = await cache.match(key);
  if (hit) {
    return notModified(hit, ifNoneMatch) ?? replayable(hit);
  }

  const built = await build();
  if (built instanceof Response) {
    return built;
  }

  const resolvedCacheControl =
    typeof cacheControl === "function" ? cacheControl(built) : cacheControl;
  const response = await cachedJson(context, built, resolvedCacheControl);
  if (response.status === 200) {
    await cache.put(key, response.clone());
  }
  return response;
}
