import { z } from "zod";

const nonEmpty = z.string().trim().min(1);
const nullableText = nonEmpty.nullable().optional();
const timestamp = z
  .string()
  .datetime({ offset: true })
  .refine((value) => value.endsWith("Z"), "timestamp must use UTC Z notation");
const sourceUrl = z.string().url().max(2048);
const isCalendarDate = (value: string): boolean => {
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value;
};
const broadcastDate = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}$/)
  .refine(isCalendarDate);

const sourceSchema = z.object({
  source_id: nonEmpty.max(100),
  name: nonEmpty.max(200),
  source_kind: nonEmpty.max(100),
  source_url: sourceUrl,
  priority: z.number().int().min(0),
  fetched_at: timestamp,
});

const channelSchema = z.object({
  channel_id: nonEmpty.max(200),
  broadcaster_id: nonEmpty.max(100),
  name: nonEmpty.max(200),
  stn: nonEmpty.max(100),
  ch: nullableText,
  city: nullableText,
  region_ids: z.array(nonEmpty.max(100)).max(20).default([]),
  radio_ids: z.array(nonEmpty.max(300)).max(20).default([]),
});

const programSchema = z.object({
  source_id: nonEmpty.max(100),
  program_id: nonEmpty.max(200),
  title: nonEmpty.max(500),
  description: z.string().max(10_000).nullable().optional(),
  hosts: z.array(nonEmpty.max(200)).max(100).default([]),
  genre: nullableText,
  homepage_url: sourceUrl.nullable().optional(),
});

const scheduleSchema = z
  .object({
    source_id: nonEmpty.max(100),
    source_url: sourceUrl,
    source_kind: nonEmpty.max(100),
    fetched_at: timestamp,
    confidence: z.number().min(0).max(1),
    channel_id: nonEmpty.max(200),
    program_id: nullableText,
    source_event_id: nullableText,
    broadcast_date: broadcastDate,
    starts_at: timestamp,
    ends_at: timestamp,
    title: nonEmpty.max(500),
    subtitle: z.string().max(1000).nullable().optional(),
    is_live: z.boolean().default(false),
    is_rerun: z.boolean().default(false),
  })
  .refine((event) => event.ends_at > event.starts_at, {
    message: "ends_at must be later than starts_at",
    path: ["ends_at"],
  });

/** 인증 ingestion이 허용하는 bounded batch 계약. */
export const importBatchSchema = z
  .object({
    idempotency_key: nonEmpty.max(200),
    source: sourceSchema,
    channels: z.array(channelSchema).max(250).default([]),
    programs: z.array(programSchema).max(1000).default([]),
    schedules: z.array(scheduleSchema).min(1).max(2000),
    images: z.array(z.unknown()).max(0).default([]),
    collected_at: timestamp,
  })
  .superRefine((batch, context) => {
    for (const program of batch.programs) {
      if (program.source_id !== batch.source.source_id) {
        context.addIssue({ code: "custom", message: "program source_id must match batch source" });
      }
    }
    for (const schedule of batch.schedules) {
      if (schedule.source_id !== batch.source.source_id) {
        context.addIssue({ code: "custom", message: "schedule source_id must match batch source" });
      }
    }
  });

export type ImportBatchInput = z.infer<typeof importBatchSchema>;
export type ImportScheduleInput = z.infer<typeof scheduleSchema>;
