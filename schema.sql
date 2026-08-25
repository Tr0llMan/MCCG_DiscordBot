-- MCCG account-linking shared schema (MySQL / MariaDB).
-- Both the Velocity plugin and the Discord bot run these statements on startup,
-- so neither component depends on the other being deployed first.

CREATE TABLE IF NOT EXISTS linked_accounts (
    minecraft_uuid CHAR(36)    NOT NULL PRIMARY KEY,
    minecraft_name VARCHAR(16) NOT NULL,
    discord_id     BIGINT      NOT NULL UNIQUE,
    linked_at      TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS link_codes (
    code           CHAR(6)     NOT NULL PRIMARY KEY,
    minecraft_uuid CHAR(36)    NOT NULL UNIQUE,   -- one active code per account
    minecraft_name VARCHAR(16) NOT NULL,
    created_at     TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Discord role -> LuckPerms group sync queue.
-- The bot enqueues a job whenever a linked member gains/loses a mapped Discord role;
-- the Velocity plugin consumes pending jobs and applies them via the LuckPerms API.
-- This is the signal channel between the two halves (no open ports / RCON needed).
CREATE TABLE IF NOT EXISTS group_sync_jobs (
    id             BIGINT      NOT NULL AUTO_INCREMENT PRIMARY KEY,
    minecraft_uuid CHAR(36)    NOT NULL,
    group_name     VARCHAR(64) NOT NULL,
    action         VARCHAR(6)  NOT NULL,           -- 'add' or 'remove'
    created_at     TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at   TIMESTAMP   NULL DEFAULT NULL,  -- NULL = still pending
    INDEX idx_group_sync_unprocessed (processed_at)
);
