import { Hono } from "hono";

import { cachedJson, errorResponse } from "../errors";
import { resolveChannel } from "../repositories/channels";
import { schedulesForDate } from "../repositories/schedules";
import type { AppEnv } from "../types";

const schedules = new Hono<AppEnv>();
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function isValidDate(value: string | undefined): value is string {
  if (!value || !DATE_PATTERN.test(value)) {
    return false;
  }
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

schedules.get("/", async (context) => {
  const date = context.req.query("date");
  if (!isValidDate(date)) {
    return errorResponse(context, 400, "invalid_date", "date must be a valid YYYY-MM-DD value.");
  }

  const identifier = context.req.query("channel_id") ?? context.req.query("radio_id");
  if (!identifier) {
    return errorResponse(
      context,
      400,
      "missing_channel",
      "channel_id or radio_id is required.",
    );
  }

  const channel = await resolveChannel(context.env.DB, identifier);
  if (!channel) {
    return errorResponse(
      context,
      404,
      "channel_not_found",
      "The requested channel alias is not registered.",
    );
  }

  const events = await schedulesForDate(context.env.DB, channel.channel_id, date, new Date());
  return cachedJson(
    context,
    {
      channel_id: channel.channel_id,
      broadcast_date: date,
      status: events.length > 0 ? "available" : "unavailable",
      stale: events.some((event) => event.source.stale),
      events,
    },
    "public, max-age=300",
  );
});

export default schedules;
