import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [, , sourceArgument, outputArgument] = process.argv;

if (!sourceArgument || !outputArgument) {
  throw new Error("Usage: sync_radio_catalog.mjs <channels.js> <output.json>");
}

const sourceUrl = pathToFileURL(resolve(sourceArgument));
const sourceModule = await import(sourceUrl.href);

if (!Array.isArray(sourceModule.CHANNELS)) {
  throw new TypeError("The source module must export a CHANNELS array");
}

const snapshot = sourceModule.CHANNELS.map((channel) => ({
  id: channel.id,
  regionId: channel.regionId,
  name: channel.name,
  stn: channel.stn,
  ch: channel.ch ?? null,
  city: channel.city ?? null,
}));
const outputPath = resolve(outputArgument);

await mkdir(dirname(outputPath), { recursive: true });
await writeFile(outputPath, `${JSON.stringify(snapshot, null, 2)}\n`, "utf8");
