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
