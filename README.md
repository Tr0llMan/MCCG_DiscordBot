# MCCG_DiscordBot
Hey there! This is mainly for the Minecraft Culling Games minecraft server hosted on UltraServers on Bukkit/Paper!

This bot purely is for linking accounts, automations, monitoring and executing commands remotely through discord.
The bot's token in production will only be accessable to the owner of this repo, all contributors who want to make modifications must
do pull requests and test with their own bot tokens for security reasons!

# How to get started?
Enter a directory you want to work in using
`cd /your/working/dir`
clone by doing
`git clone https://github.com/Tr0llMan/MCCG_DiscordBot.git`

before doing changes please always do a `git pull` or `git checkout -b feature-yourfeaturename` to create a local branch,
no one should be working inside the `main` branch other than the repo owner!

# How to commit?
When finishing a task, do `git add * ; git commit -am "[very very short reason for changes]"`
this will add all the new files you have created, commit them to the version control.
Do `git push` or `git push --set-upstream origin feature-yourfeaturename` (only on new local branches) to push them to the repo!

When you are done creating your feature, create a *pull request* by click on the *link provided by the `git push` command* and fill out the forum,
this will create a request for the owner to verify your code and merge it to main.

# Whats currently in the works and what is done?
Working on:
- /link command in minecraft -> discord account linking
Done:
- Discord role -> LuckPerms group sync (in-house, no extra plugins/bots). The bot queues role
  changes in the shared DB; the MCCGDiscord Velocity plugin applies them via the LuckPerms API.

## Discord role -> LuckPerms group sync
We sync ranks ourselves instead of using DiscordSRV, because our host (UltraServers) exposes
no SSH/firewall — so RCON can't be secured and any extra bot/port is unwanted. Instead:

1. The bot watches `on_member_update`; when a **linked** member gains/loses a role listed in
   `ROLE_GROUP_MAP`, it inserts a row into the `group_sync_jobs` table (shared MySQL).
2. The MCCGDiscord Velocity plugin (where LuckPerms runs with shared MySQL storage) polls that
   table and applies each change via the LuckPerms API in-process. Changes propagate to the
   backends automatically. Nothing new listens on the network — only outbound DB reads.

Setup:
- Edit **`rolemap.toml`** (repo root) — the `[roles]` table maps Discord role IDs to LuckPerms
  group names. It's not a secret; commit it. Empty = sync disabled. Restart the bot to apply.
- Enable the **Server Members** privileged intent in the Discord Developer Portal (Bot ->
  Privileged Gateway Intents) — required for role-change events; the bot only requests it when
  `rolemap.toml` has at least one mapping.
- Ensure LuckPerms is on the proxy with **MySQL/shared storage** so changes reach the backends.
- Tune polling in the MCCGDiscord `config.toml` under `[group-sync]` (defaults: 10s, batch 50).
