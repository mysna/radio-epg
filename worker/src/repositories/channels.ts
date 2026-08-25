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

const CHANNEL_COLUMNS = `
    channels.id AS channel_id,
    channels.name,
    channels.region_id,
    channels.stn,
    channels.ch,
    channels.city,
    channels.active,
    broadcasters.id AS broadcaster_id,
    broadcasters.name AS broadcaster_name
`;

const CHANNEL_SELECT = `
  SELECT ${CHANNEL_COLUMNS}
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

/**
 * 여러 식별자를 한 번의 질의로 채널 ID에 대응시킨다. 별칭 목록이 필요 없는
 * 경로에서 채널마다 조회를 반복하지 않기 위한 경량 lookup이다.
 */
export async function resolveChannelIds(
  database: Database,
  identifiers: string[],
): Promise<Map<string, string>> {
  if (identifiers.length === 0) {
    return new Map();
  }
  const result = await database
    .prepare(
      `SELECT identifier, channel_id, MIN(match_rank) AS match_rank
       FROM (
         SELECT requested.value AS identifier, channels.id AS channel_id, 0 AS match_rank
         FROM json_each(?1) AS requested
         JOIN channels ON channels.id = requested.value
         WHERE channels.active = 1
         UNION ALL
         SELECT requested.value AS identifier, channels.id AS channel_id, 1 AS match_rank
         FROM json_each(?1) AS requested
         JOIN channel_aliases ON channel_aliases.alias_value = requested.value
         JOIN channels ON channels.id = channel_aliases.channel_id
         WHERE channels.active = 1
       )
       GROUP BY identifier`,
    )
    .bind(JSON.stringify(identifiers))
    .all<{ identifier: string; channel_id: string }>();
  return new Map(result.results.map((row) => [row.identifier, row.channel_id]));
}

/** 정규 ID 또는 등록된 별칭으로 활성 채널 하나를 조회한다. */
export async function resolveChannel(
  database: Database,
  identifier: string,
): Promise<PublicChannel | null> {
  // 두 테이블에 걸친 OR은 인덱스를 쓰지 못하므로 갈래별 조회를 UNION으로 합친다.
  const row = await database
    .prepare(
      `SELECT ${CHANNEL_COLUMNS}, 0 AS match_rank
       FROM channels
       JOIN broadcasters ON broadcasters.id = channels.broadcaster_id
       WHERE channels.active = 1 AND channels.id = ?1
       UNION ALL
       SELECT ${CHANNEL_COLUMNS}, 1 AS match_rank
       FROM channel_aliases
       JOIN channels ON channels.id = channel_aliases.channel_id
       JOIN broadcasters ON broadcasters.id = channels.broadcaster_id
       WHERE channels.active = 1 AND channel_aliases.alias_value = ?1
       ORDER BY match_rank
       LIMIT 1`,
    )
    .bind(identifier)
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
