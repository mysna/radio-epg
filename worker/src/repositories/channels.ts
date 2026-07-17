import type { Database } from "../db";
import type { ChannelAlias, PublicChannel } from "../types";

interface ChannelRow {
  channel_id: string;
  name: string;
  region_id: string | null;
  stn: string;
  ch: string | null;
  city: string | null;
  active: number;
  broadcaster_id: string;
  broadcaster_name: string;
}

interface AliasRow {
  channel_id: string;
  alias_type: string;
  alias_value: string;
}

const CHANNEL_SELECT = `
  SELECT
    channels.id AS channel_id,
    channels.name,
    channels.region_id,
    channels.stn,
    channels.ch,
    channels.city,
    channels.active,
    broadcasters.id AS broadcaster_id,
    broadcasters.name AS broadcaster_name
  FROM channels
  JOIN broadcasters ON broadcasters.id = channels.broadcaster_id
`;

function toPublicChannel(row: ChannelRow, aliases: ChannelAlias[]): PublicChannel {
  return {
    channel_id: row.channel_id,
    name: row.name,
    region_id: row.region_id,
    stn: row.stn,
    ch: row.ch,
    city: row.city,
    active: row.active === 1,
    broadcaster: { id: row.broadcaster_id, name: row.broadcaster_name },
    aliases,
  };
}

async function aliasesByChannel(database: Database): Promise<Map<string, ChannelAlias[]>> {
  const result = await database
    .prepare(
      "SELECT channel_id, alias_type, alias_value FROM channel_aliases ORDER BY alias_type, alias_value",
    )
    .all<AliasRow>();
  const aliases = new Map<string, ChannelAlias[]>();

  for (const row of result.results) {
    const values = aliases.get(row.channel_id) ?? [];
    values.push({ type: row.alias_type, value: row.alias_value });
    aliases.set(row.channel_id, values);
  }
  return aliases;
}

/** 활성 채널 전체를 정규 ID 순서로 조회한다. */
export async function listChannels(database: Database): Promise<PublicChannel[]> {
  const [channelResult, aliases] = await Promise.all([
    database.prepare(`${CHANNEL_SELECT} WHERE channels.active = 1 ORDER BY channels.id`).all<ChannelRow>(),
    aliasesByChannel(database),
  ]);

  return channelResult.results.map((row) => toPublicChannel(row, aliases.get(row.channel_id) ?? []));
}

/** 정규 ID 또는 등록된 별칭으로 활성 채널 하나를 조회한다. */
export async function resolveChannel(
  database: Database,
  identifier: string,
): Promise<PublicChannel | null> {
  const row = await database
    .prepare(
      `${CHANNEL_SELECT}
       LEFT JOIN channel_aliases ON channel_aliases.channel_id = channels.id
       WHERE channels.active = 1
         AND (channels.id = ? OR channel_aliases.alias_value = ?)
       ORDER BY CASE WHEN channels.id = ? THEN 0 ELSE 1 END
       LIMIT 1`,
    )
    .bind(identifier, identifier, identifier)
    .first<ChannelRow>();

  if (!row) {
    return null;
  }

  const aliasResult = await database
    .prepare(
      "SELECT channel_id, alias_type, alias_value FROM channel_aliases WHERE channel_id = ? ORDER BY alias_type, alias_value",
    )
    .bind(row.channel_id)
    .all<AliasRow>();
  const aliases = aliasResult.results.map((alias) => ({
    type: alias.alias_type,
    value: alias.alias_value,
  }));
  return toPublicChannel(row, aliases);
}
