ALTER TABLE broadcasters DROP COLUMN image_asset_id;
ALTER TABLE channels DROP COLUMN image_asset_id;
ALTER TABLE programs DROP COLUMN image_asset_id;
ALTER TABLE scrape_runs DROP COLUMN image_count;

DROP TABLE image_variants;
DROP TABLE image_takedowns;
DROP TABLE image_assets;
