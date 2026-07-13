import { env } from "cloudflare:workers";
import { applyD1Migrations, type D1Migration } from "cloudflare:test";
import { beforeAll, describe, expect, it } from "vitest";

import app from "../src/index";

const TOKEN = "test-ingest-token";
const PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgQIAKfWfWQAAAABJRU5ErkJggg==";
const testEnv = env as typeof env & {
  DB: D1Database;
  IMAGES: R2Bucket;
  TEST_MIGRATIONS: D1Migration[];
};
const bindings = {
  DB: testEnv.DB,
  IMAGES: testEnv.IMAGES,
  CORS_ORIGINS: "https://radio.bsod.kr",
  INGEST_TOKEN: TOKEN,
};

function decodeBase64(value: string): Uint8Array {
  return Uint8Array.from(atob(value), (character) => character.charCodeAt(0));
}

async function seedProgram(suffix: string): Promise<{ sourceId: string; programId: string }> {
  const sourceId = `image-source-${suffix}`;
  const programId = `image-program-${suffix}`;
  await testEnv.DB.batch([
    testEnv.DB.prepare(
      "INSERT INTO sources (id, name, kind, base_url, priority) VALUES (?, ?, 'official', ?, 100)",
    ).bind(sourceId, `Image source ${suffix}`, "https://images.example.test/"),
    testEnv.DB.prepare(
      "INSERT INTO programs (id, source_id, upstream_id, title) VALUES (?, ?, ?, ?)",
    ).bind(programId, sourceId, programId, `Image program ${suffix}`),
  ]);
  return { sourceId, programId };
}

function imagePayload(
  suffix: string,
  sourceId: string,
  programId: string,
  variantName: "small" | "medium" | "original" = "small",
) {
  const hashPair = suffix.charCodeAt(0).toString(16).padStart(2, "0");
  const contentHash = hashPair.repeat(32);
  return {
    asset: {
      source_id: sourceId,
      entity_type: "program",
      entity_id: programId,
      content_hash: contentHash,
      rights_status: "unknown",
      source_url: `https://images.example.test/${suffix}.png`,
      source_page_url: `https://program.example.test/${suffix}`,
      author: null,
      license: null,
      attribution: null,
      verified_at: "2026-07-13T01:00:00Z",
    },
    variant: {
      name: variantName,
      mime_type: "image/png",
      width: 1,
      height: 1,
      byte_size: decodeBase64(PNG_BASE64).byteLength,
      content_base64: PNG_BASE64,
    },
  };
}

async function adminPost(path: string, body: unknown, token: string | null = TOKEN) {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (token !== null) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return app.request(
    `https://api.example.test${path}`,
    { method: "POST", headers, body: JSON.stringify(body) },
    bindings,
  );
}

beforeAll(async () => {
  await applyD1Migrations(testEnv.DB, testEnv.TEST_MIGRATIONS);
});

describe("image ingestion, serving, and takedown", () => {
  it("requires bearer authentication for image writes", async () => {
    const response = await adminPost("/v1/admin/images", {}, null);

    expect(response.status).toBe(401);
  });

  it("stores one validated variant in R2 and D1 and serves it publicly", async () => {
    const { sourceId, programId } = await seedProgram("serve");
    const payload = imagePayload("serve", sourceId, programId);
    const response = await adminPost("/v1/admin/images", payload);
    const contentHash = payload.asset.content_hash;
    const stored = await testEnv.IMAGES.get(`images/${contentHash}/small.png`);
    const linked = await testEnv.DB.prepare("SELECT image_asset_id FROM programs WHERE id = ?")
      .bind(programId)
      .first<{ image_asset_id: string | null }>();

    expect(response.status).toBe(201);
    expect(stored && new Uint8Array(await stored.arrayBuffer())).toEqual(decodeBase64(PNG_BASE64));
    expect(linked?.image_asset_id).toBe(contentHash);

    const publicResponse = await app.request(
      `https://api.example.test/v1/images/${contentHash}/small`,
      {},
      bindings,
    );
    expect(publicResponse.status).toBe(200);
    expect(publicResponse.headers.get("Content-Type")).toBe("image/png");
    expect(publicResponse.headers.get("Cache-Control")).toContain("immutable");
  });

  it("rejects a declared MIME type that does not match the bytes", async () => {
    const { sourceId, programId } = await seedProgram("mime");
    const payload = imagePayload("mime", sourceId, programId);
    payload.variant.mime_type = "image/jpeg";

    const response = await adminPost("/v1/admin/images", payload);

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toMatchObject({ error: { code: "invalid_image" } });
  });

  it("rejects non-HTTPS provenance URLs", async () => {
    const { sourceId, programId } = await seedProgram("insecure");
    const payload = imagePayload("insecure", sourceId, programId);
    payload.asset.source_url = "http://127.0.0.1/private.png";

    const response = await adminPost("/v1/admin/images", payload);

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toMatchObject({ error: { code: "invalid_image" } });
  });

  it("deduplicates asset metadata by content hash while storing distinct variants", async () => {
    const { sourceId, programId } = await seedProgram("dedupe");
    const small = imagePayload("dedupe", sourceId, programId, "small");
    const medium = imagePayload("dedupe", sourceId, programId, "medium");

    expect((await adminPost("/v1/admin/images", small)).status).toBe(201);
    expect((await adminPost("/v1/admin/images", medium)).status).toBe(201);
    const assets = await testEnv.DB.prepare("SELECT COUNT(*) AS count FROM image_assets WHERE content_hash = ?")
      .bind(small.asset.content_hash)
      .first<{ count: number }>();
    const variants = await testEnv.DB.prepare("SELECT COUNT(*) AS count FROM image_variants WHERE asset_id = ?")
      .bind(small.asset.content_hash)
      .first<{ count: number }>();

    expect(assets?.count).toBe(1);
    expect(variants?.count).toBe(2);
  });

  it("removes an R2 object when the D1 metadata write fails", async () => {
    const payload = imagePayload("rollback", "missing-source", "missing-program");
    const response = await adminPost("/v1/admin/images", payload);
    const stored = await testEnv.IMAGES.get(`images/${payload.asset.content_hash}/small.png`);

    expect(response.status).toBe(500);
    expect(stored).toBeNull();
  });

  it("marks assets unavailable, deletes variants, and permanently blocks re-import", async () => {
    const { sourceId, programId } = await seedProgram("takedown");
    const payload = imagePayload("takedown", sourceId, programId);
    expect((await adminPost("/v1/admin/images", payload)).status).toBe(201);
    const second = await seedProgram("takedown-second");
    const secondPayload = imagePayload(
      "takedown",
      second.sourceId,
      second.programId,
      "medium",
    );
    expect((await adminPost("/v1/admin/images", secondPayload)).status).toBe(201);

    const response = await adminPost("/v1/admin/takedown", {
      asset_id: payload.asset.content_hash,
      reason: "rights holder request",
      requested_at: "2026-07-13T02:00:00Z",
    });
    const asset = await testEnv.DB.prepare(
      "SELECT available, content_hash, source_url FROM image_assets WHERE id = ?",
    )
      .bind(payload.asset.content_hash)
      .first<{ available: number; content_hash: string; source_url: string }>();
    const takedown = await testEnv.DB.prepare(
      "SELECT content_hash, source_url, permanent_block FROM image_takedowns WHERE asset_id = ?",
    )
      .bind(payload.asset.content_hash)
      .first<{ content_hash: string; source_url: string; permanent_block: number }>();
    const links = await testEnv.DB.prepare(
      "SELECT image_asset_id FROM programs WHERE id IN (?, ?) ORDER BY id",
    )
      .bind(programId, second.programId)
      .all<{ image_asset_id: string | null }>();

    expect(response.status).toBe(200);
    expect(asset?.available).toBe(0);
    expect(takedown).toMatchObject({
      content_hash: asset?.content_hash,
      source_url: asset?.source_url,
      permanent_block: 1,
    });
    expect(links.results.map(({ image_asset_id }) => image_asset_id)).toEqual([null, null]);
    expect(await testEnv.IMAGES.get(`images/${payload.asset.content_hash}/small.png`)).toBeNull();
    expect((await adminPost("/v1/admin/images", payload)).status).toBe(409);
    expect(
      (
        await app.request(
          `https://api.example.test/v1/images/${payload.asset.content_hash}/small`,
          {},
          bindings,
        )
      ).status,
    ).toBe(404);
  });
});
