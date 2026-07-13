import { Hono } from "hono";
import { z } from "zod";

import { isAuthorized } from "../auth";
import { errorResponse } from "../errors";
import type { AppEnv } from "../types";

const MAX_IMAGE_BODY_BYTES = 7_000_000;
const MAX_VARIANT_BYTES = 5_000_000;
const MAX_PIXELS = 16_000_000;
const nullableText = z.string().trim().min(1).max(2_000).nullable().optional();
const httpsUrl = z
  .string()
  .url()
  .max(2_048)
  .refine((value) => new URL(value).protocol === "https:", "URL must use HTTPS");
const utcTimestamp = z
  .string()
  .datetime({ offset: true })
  .refine((value) => value.endsWith("Z"), "timestamp must use UTC Z notation");

const imageIngestSchema = z.object({
  asset: z.object({
    source_id: z.string().trim().min(1).max(100).nullable().optional(),
    entity_type: z.enum(["broadcaster", "channel", "program"]),
    entity_id: z.string().trim().min(1).max(200),
    content_hash: z.string().regex(/^[a-f0-9]{64}$/),
    rights_status: z.string().trim().min(1).max(100),
    source_url: httpsUrl,
    source_page_url: httpsUrl,
    author: nullableText,
    license: nullableText,
    attribution: nullableText,
    verified_at: utcTimestamp,
  }),
  variant: z
    .object({
      name: z.enum(["small", "medium", "original"]),
      mime_type: z.enum(["image/png", "image/jpeg", "image/webp"]),
      width: z.number().int().min(1).max(4_096),
      height: z.number().int().min(1).max(4_096),
      byte_size: z.number().int().min(1).max(MAX_VARIANT_BYTES),
      content_base64: z.string().min(1).max(6_700_000),
    })
    .refine((variant) => variant.width * variant.height <= MAX_PIXELS, {
      message: "variant exceeds pixel limit",
    }),
});

type ImageIngest = z.infer<typeof imageIngestSchema>;

function decodeBase64(value: string): Uint8Array | null {
  if (value.length % 4 !== 0 || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) {
    return null;
  }
  try {
    return Uint8Array.from(atob(value), (character) => character.charCodeAt(0));
  } catch {
    return null;
  }
}

function sniffMime(bytes: Uint8Array): string | null {
  if (
    bytes.length >= 8 &&
    bytes[0] === 0x89 &&
    bytes[1] === 0x50 &&
    bytes[2] === 0x4e &&
    bytes[3] === 0x47 &&
    bytes[4] === 0x0d &&
    bytes[5] === 0x0a &&
    bytes[6] === 0x1a &&
    bytes[7] === 0x0a
  ) {
    return "image/png";
  }
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
    return "image/jpeg";
  }
  if (
    bytes.length >= 12 &&
    new TextDecoder().decode(bytes.slice(0, 4)) === "RIFF" &&
    new TextDecoder().decode(bytes.slice(8, 12)) === "WEBP"
  ) {
    return "image/webp";
  }
  return null;
}

function extensionFor(mimeType: ImageIngest["variant"]["mime_type"]): string {
  return { "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp" }[mimeType];
}

function linkStatement(database: D1Database, input: ImageIngest): D1PreparedStatement {
  const table = {
    broadcaster: "broadcasters",
    channel: "channels",
    program: "programs",
  }[input.asset.entity_type];
  return database
    .prepare(`UPDATE ${table} SET image_asset_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?`)
    .bind(input.asset.content_hash, input.asset.entity_id);
}

async function isBlocked(database: D1Database, contentHash: string, sourceUrl: string) {
  return database
    .prepare(
      `SELECT id FROM image_takedowns
       WHERE permanent_block = 1 AND (content_hash = ? OR source_url = ?)
       LIMIT 1`,
    )
    .bind(contentHash, sourceUrl)
    .first<{ id: string }>();
}

const adminImages = new Hono<AppEnv>();

adminImages.post("/", async (context) => {
  const token = context.env.INGEST_TOKEN;
  if (!token) {
    return errorResponse(context, 500, "ingest_not_configured", "Ingestion is not configured.");
  }
  if (!isAuthorized(context.req.header("Authorization"), token)) {
    return errorResponse(context, 401, "unauthorized", "A valid bearer token is required.");
  }

  const rawBody = await context.req.text();
  if (new TextEncoder().encode(rawBody).byteLength > MAX_IMAGE_BODY_BYTES) {
    return errorResponse(context, 413, "request_too_large", "Image request is too large.");
  }

  let rawInput: unknown;
  try {
    rawInput = JSON.parse(rawBody);
  } catch {
    return errorResponse(context, 400, "invalid_image", "Image request must be valid JSON.");
  }
  const parsed = imageIngestSchema.safeParse(rawInput);
  if (!parsed.success) {
    return errorResponse(context, 400, "invalid_image", "Image request does not match the schema.");
  }

  const bytes = decodeBase64(parsed.data.variant.content_base64);
  if (
    bytes === null ||
    bytes.byteLength !== parsed.data.variant.byte_size ||
    sniffMime(bytes) !== parsed.data.variant.mime_type
  ) {
    return errorResponse(context, 400, "invalid_image", "Image bytes do not match their metadata.");
  }
  if (await isBlocked(context.env.DB, parsed.data.asset.content_hash, parsed.data.asset.source_url)) {
    return errorResponse(context, 409, "image_blocked", "This image is permanently blocked.");
  }

  const extension = extensionFor(parsed.data.variant.mime_type);
  const r2Key = `images/${parsed.data.asset.content_hash}/${parsed.data.variant.name}.${extension}`;
  try {
    await context.env.IMAGES.put(r2Key, bytes, {
      httpMetadata: {
        contentType: parsed.data.variant.mime_type,
        cacheControl: "public, max-age=31536000, immutable",
      },
    });
  } catch {
    return errorResponse(context, 500, "image_store_failed", "The image could not be stored.");
  }

  try {
    await context.env.DB.batch([
      context.env.DB
        .prepare(
          `INSERT INTO image_assets (
             id, source_id, entity_type, entity_id, content_hash, rights_status,
             source_url, source_page_url, author, license, attribution,
             first_verified_at, last_verified_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(content_hash) DO UPDATE SET
             rights_status = excluded.rights_status,
             source_url = excluded.source_url,
             source_page_url = excluded.source_page_url,
             author = excluded.author,
             license = excluded.license,
             attribution = excluded.attribution,
             last_verified_at = excluded.last_verified_at`,
        )
        .bind(
          parsed.data.asset.content_hash,
          parsed.data.asset.source_id ?? null,
          parsed.data.asset.entity_type,
          parsed.data.asset.entity_id,
          parsed.data.asset.content_hash,
          parsed.data.asset.rights_status,
          parsed.data.asset.source_url,
          parsed.data.asset.source_page_url,
          parsed.data.asset.author ?? null,
          parsed.data.asset.license ?? null,
          parsed.data.asset.attribution ?? null,
          parsed.data.asset.verified_at,
          parsed.data.asset.verified_at,
        ),
      context.env.DB
        .prepare(
          `INSERT INTO image_variants (
             asset_id, variant_name, mime_type, width, height, byte_size, r2_key
           ) VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(asset_id, variant_name) DO UPDATE SET
             mime_type = excluded.mime_type,
             width = excluded.width,
             height = excluded.height,
             byte_size = excluded.byte_size,
             r2_key = excluded.r2_key`,
        )
        .bind(
          parsed.data.asset.content_hash,
          parsed.data.variant.name,
          parsed.data.variant.mime_type,
          parsed.data.variant.width,
          parsed.data.variant.height,
          parsed.data.variant.byte_size,
          r2Key,
        ),
      linkStatement(context.env.DB, parsed.data),
    ]);
  } catch {
    await context.env.IMAGES.delete(r2Key);
    return errorResponse(context, 500, "image_metadata_failed", "Image metadata could not be stored.");
  }

  return context.json(
    {
      status: "stored",
      asset_id: parsed.data.asset.content_hash,
      variant: parsed.data.variant.name,
      url: `/v1/images/${parsed.data.asset.content_hash}/${parsed.data.variant.name}`,
    },
    201,
  );
});

export default adminImages;
