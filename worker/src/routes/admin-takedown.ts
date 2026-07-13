import { Hono } from "hono";
import { z } from "zod";

import { isAuthorized } from "../auth";
import { errorResponse } from "../errors";
import type { AppEnv } from "../types";

const takedownSchema = z.object({
  asset_id: z.string().regex(/^[a-f0-9]{64}$/),
  reason: z.string().trim().min(1).max(2_000),
  requested_at: z
    .string()
    .datetime({ offset: true })
    .refine((value) => value.endsWith("Z"), "timestamp must use UTC Z notation"),
});

interface TakedownAsset {
  id: string;
  content_hash: string;
  source_url: string;
}

function unlinkStatements(database: D1Database, assetId: string): D1PreparedStatement[] {
  return ["broadcasters", "channels", "programs"].map((table) =>
    database
      .prepare(
        `UPDATE ${table}
         SET image_asset_id = NULL, updated_at = CURRENT_TIMESTAMP
         WHERE image_asset_id = ?`,
      )
      .bind(assetId),
  );
}

const adminTakedown = new Hono<AppEnv>();

adminTakedown.post("/", async (context) => {
  const token = context.env.INGEST_TOKEN;
  if (!token) {
    return errorResponse(context, 500, "ingest_not_configured", "Ingestion is not configured.");
  }
  if (!isAuthorized(context.req.header("Authorization"), token)) {
    return errorResponse(context, 401, "unauthorized", "A valid bearer token is required.");
  }

  let rawInput: unknown;
  try {
    rawInput = await context.req.json();
  } catch {
    return errorResponse(context, 400, "invalid_takedown", "Takedown request must be valid JSON.");
  }
  const parsed = takedownSchema.safeParse(rawInput);
  if (!parsed.success) {
    return errorResponse(context, 400, "invalid_takedown", "Takedown request is invalid.");
  }

  const asset = await context.env.DB.prepare(
    "SELECT id, content_hash, source_url FROM image_assets WHERE id = ?",
  )
    .bind(parsed.data.asset_id)
    .first<TakedownAsset>();
  if (!asset) {
    return errorResponse(context, 404, "image_not_found", "The requested image was not found.");
  }
  const variants = await context.env.DB.prepare(
    "SELECT r2_key FROM image_variants WHERE asset_id = ?",
  )
    .bind(asset.id)
    .all<{ r2_key: string }>();

  await context.env.DB.batch([
    context.env.DB.prepare("UPDATE image_assets SET available = 0 WHERE id = ?").bind(asset.id),
    ...unlinkStatements(context.env.DB, asset.id),
    context.env.DB
      .prepare(
        `INSERT INTO image_takedowns (
           id, asset_id, content_hash, source_url, reason, requested_at,
           completed_at, permanent_block
         ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)`,
      )
      .bind(
        crypto.randomUUID(),
        asset.id,
        asset.content_hash,
        asset.source_url,
        parsed.data.reason,
        parsed.data.requested_at,
        parsed.data.requested_at,
      ),
  ]);

  try {
    const keys = variants.results.map(({ r2_key: key }) => key);
    if (keys.length > 0) {
      await context.env.IMAGES.delete(keys);
    }
  } catch {
    return errorResponse(context, 500, "image_delete_failed", "Image objects could not be deleted.");
  }

  return context.json({ status: "removed", asset_id: asset.id }, 200);
});

export default adminTakedown;
