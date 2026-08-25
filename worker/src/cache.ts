import type { Context } from "hono";

import { cachedJson } from "./errors";
import type { AppEnv } from "./types";

/** WebWorker lib의 CacheStorage 타입에는 없는 Cloudflare 기본 캐시를 가져온다. */
function edgeCache(): Cache {
  return (caches as unknown as { default: Cache }).default;
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
 * 오류 응답으로 보고 캐시하지 않는다.
 */
export async function edgeCachedJson(
  context: Context<AppEnv>,
  cacheControl: string,
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

  const response = await cachedJson(context, built, cacheControl);
  if (response.status === 200) {
    await cache.put(key, response.clone());
  }
  return response;
}
