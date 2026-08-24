-- One-time (and re-runnable) import of existing MCCG links into DiscordSRV.
--
-- Context:
--   DiscordSRV's group-role synchronization only reads its OWN accounts table, not our
--   `linked_accounts` table. To avoid forcing everyone to relink, we copy our existing
--   links into DiscordSRV's table. Both tables live in the SAME database.
--
-- Prerequisites:
--   1. Run DiscordSRV at least once with its JDBC backend enabled and pointed at this DB
--      (config.yml -> Experiment_JdbcAccountLinkBackend / Experiment_JdbcTablePrefix:
--      "discordsrv_"). That boot creates `discordsrv_accounts` and `discordsrv_codes`.
--   2. Then run this script against the shared database.
--
-- Notes:
--   - INSERT IGNORE makes this safe to run repeatedly (skips rows already present) and
--     doubles as the periodic reconciliation job (e.g. a daily cron) to backfill any link
--     the bot's live mirror missed while DiscordSRV was offline.
--   - `discord` is VARCHAR(32) in DiscordSRV; our `discord_id` is BIGINT, hence the CAST.
--   - `uuid` matches directly: both are 36-char, lowercase, dashed Mojang UUIDs.
--   - If you set a different Experiment_JdbcTablePrefix, change the table name below.

INSERT IGNORE INTO discordsrv_accounts (discord, uuid)
SELECT CAST(discord_id AS CHAR), minecraft_uuid
FROM linked_accounts;

-- Sanity check: these two counts should match (allowing for any pre-existing DiscordSRV rows).
--   SELECT COUNT(*) AS ours FROM linked_accounts;
--   SELECT COUNT(*) AS discordsrv FROM discordsrv_accounts;
