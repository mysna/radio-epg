import { Hono } from "hono";

import { errorResponse } from "../errors";
import type { AppEnv } from "../types";

interface StoredImage {
  r2_key: string;
  mime_type: string;
  content_hash: string;
}

const images = new Hono<AppEnv>();

images.get("/:assetId/:variant", async (context) => {
  const assetId = context.req.param("assetId");
  const variant = context.req.param("variant");
  if (!/^[a-f0-9]{64}$/.test(assetId) || !["small", "medium", "original"].includes(variant)) {
    return errorResponse(context, 404, "image_not_found", "The requested image was not found.");
  }

  const metadata = await context.env.DB.prepare(
    `SELECT v.r2_key, v.mime_type, a.content_hash
     FROM image_assets a
     JOIN image_variants v ON v.asset_id = a.id
     WHERE a.id = ? AND a.available = 1 AND v.variant_name = ?`,
  )
    .bind(assetId, variant)
    .first<StoredImage>();
  if (!metadata) {
    return errorResponse(context, 404, "image_not_found", "The requested image was not found.");
  }

  const object = await context.env.IMAGES.get(metadata.r2_key);
  if (!object) {
    return errorResponse(context, 404, "image_not_found", "The requested image was not found.");
  }

  const headers = new Headers({
    "Cache-Control": "public, max-age=31536000, immutable",
    "Content-Type": metadata.mime_type,
    ETag: object.httpEtag,
  });
  return new Response(object.body, { status: 200, headers });
});

export default images;
