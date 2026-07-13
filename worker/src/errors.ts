import type { Context } from "hono";

import type { AppEnv } from "./types";

type ErrorStatus = 400 | 401 | 403 | 404 | 409 | 413 | 500;

/** 안정적인 공개 오류 envelope를 반환한다. */
export function errorResponse(
  context: Context<AppEnv>,
  status: ErrorStatus,
  code: string,
  message: string,
): Response {
  return context.json({ error: { code, message } }, status);
}

function bytesToHex(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** JSON 응답에 결정적인 ETag와 route별 캐시 정책을 적용한다. */
export async function cachedJson(
  context: Context<AppEnv>,
  body: unknown,
  cacheControl: string,
): Promise<Response> {
  const json = JSON.stringify(body);
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(json));
  const etag = `"${bytesToHex(digest)}"`;
  const headers = new Headers({
    "Cache-Control": cacheControl,
    "Content-Type": "application/json; charset=UTF-8",
    ETag: etag,
  });

  if (context.req.header("If-None-Match") === etag) {
    return context.newResponse(null, { status: 304, headers });
  }
  return context.newResponse(json, { status: 200, headers });
}
