import type { DatabaseBindings } from "./db";

/** Worker가 요청 처리 중 사용하는 환경 binding. */
export interface Bindings extends DatabaseBindings {
  CORS_ORIGINS?: string;
  INGEST_TOKEN?: string;
}

/** Hono 애플리케이션의 환경 타입. */
export interface AppEnv {
  Bindings: Bindings;
}

/** 공개 API가 반환하는 채널 별칭. */
export interface ChannelAlias {
  type: string;
  value: string;
}

/** 공개 API의 정규화 채널 응답. */
export interface PublicChannel {
  channel_id: string;
  name: string;
  region_id: string | null;
  stn: string;
  ch: string | null;
  city: string | null;
  active: boolean;
  broadcaster: { id: string; name: string };
  aliases: ChannelAlias[];
}

/** 편성 출처와 freshness 정보. */
export interface PublicSource {
  id: string;
  url: string;
  kind: string;
  fetched_at: string;
  confidence: number;
  stale: boolean;
}

/** 공개 API가 반환하는 편성 이벤트. */
export interface PublicScheduleEvent {
  event_id: string;
  program_id: string | null;
  title: string;
  subtitle: string | null;
  starts_at: string;
  ends_at: string;
  is_live: boolean;
  is_rerun: boolean;
  source: PublicSource;
}
