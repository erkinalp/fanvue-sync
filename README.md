# Fanvue Sync

Tools to apply perks to your Discord or Matrix communities based on Fanvue memberships, and vice versa.

## Overview

Fanvue Sync provides two synchronization tools that bridge your Fanvue creator account with your community platforms:

**fanvue-discord-sync** grants Discord roles to users based on their Fanvue subscription status, spending history, or content purchases. It also supports "double upsell" - sending promotional messages to Discord premium members or server boosters.

**fanvue-matrix-sync** manages Matrix room membership based on Fanvue entitlements, automatically inviting qualified users and removing those whose subscriptions have expired.

Both tools share a common library (`fanvue_common`) that handles Fanvue API authentication, rate limiting, and membership computation logic.

## Features

Role/room assignment based on subscription status (active subscribers), lifetime spending thresholds (e.g., users who spent $100+), top spender status (Fanvue's native flag), specific content unlocks (users who purchased a particular post), and Fanvue list membership.

The Discord bot additionally supports upselling to users who purchase Discord SKUs or boost the server, with configurable promotional messages.

**Auto-Join to Guild**: Like Patreon and Gumroad sync bots, users who link their Discord account via OAuth can be automatically added to your Discord server when they have an active Fanvue membership. This requires Discord OAuth with the `guilds.join` scope.

**Bidirectional List Sync**: Sync between Fanvue custom lists and Discord roles with either side as primary. When Fanvue is primary, list members get the Discord role. When Discord is primary, role members are added to the Fanvue list.

Expiry policies let you choose whether to remove roles/kick users, or grandfather them when their entitlement lapses.

## Installation

### Prerequisites

You need Python 3.8+ and a Fanvue developer application. Create one at https://fanvue.com/developers/apps to obtain your client ID and secret.

### Discord Sync

```bash
cd fanvue-discord-sync
pip install -r requirements.txt
cp config.yaml.example config.yaml
# Edit config.yaml with your credentials
python -m fanvue_discord_sync.main
```

### Matrix Sync

```bash
cd fanvue-matrix-sync
pip install -r requirements.txt
cp config.yaml.example config.yaml
# Edit config.yaml with your credentials
python -m fanvue_matrix_sync.main
```

On first run, you'll be prompted to authorize via Fanvue OAuth. The tokens are saved to `fanvue_tokens.json` for subsequent runs.

## Configuration

### Discord Configuration

```yaml
fanvue:
  client_id: "your_client_id"
  client_secret: "your_client_secret"
  redirect_uri: "http://localhost:8080/callback"

discord:
  token: "your_discord_bot_token"
  guild_id: 123456789012345678
  # Discord OAuth settings for auto-join feature (optional)
  oauth_client_id: "your_discord_oauth_client_id"
  oauth_client_secret: "your_discord_oauth_client_secret"
  oauth_redirect_uri: "http://localhost:8080/callback"
  oauth_server_host: "0.0.0.0"
  oauth_server_port: 8080

roles:
  "987654321098765432":  # Discord Role ID
    type: "subscription"
    active_subscription: true
    on_expiry: "remove_role"  # or "kick" or "ignore"

  "112233445566778899":
    type: "spending"
    min_lifetime_spend_cents: 50000  # $500

  "998877665544332211":
    type: "top_spender"

  "555555555555555555":
    type: "unlock"
    content_id: "uuid-of-the-content"

  "666666666666666666":
    type: "fanvue_list"
    list_uuid: "uuid-of-fanvue-custom-list"
    list_type: "custom"  # or "smart"

# Auto-join configuration (requires Discord OAuth)
auto_join:
  enabled: true
  roles:  # Optional: roles to assign on join
    - "987654321098765432"

# Bidirectional list sync configuration
list_sync:
  vip_sync:
    discord_role_id: "111111111111111111"
    fanvue_list_uuid: "uuid-of-fanvue-list"
    fanvue_list_type: "custom"
    primary: "fanvue"  # or "discord"
  
  moderators_sync:
    discord_role_id: "222222222222222222"
    fanvue_list_uuid: "uuid-of-moderators-list"
    fanvue_list_type: "custom"
    primary: "discord"  # Discord role members sync to Fanvue list

upsell:
  required_entitlement_ids:
    - "123456789012345678"
  upsell_on_boost: true
  offer_message: |
    Hey there! Thanks for your support on Discord!
    Here is a special offer for my Fanvue page:
    https://fanvue.com/myprofile?promo=DISCORDVIP20
```

### Matrix Configuration

```yaml
fanvue:
  client_id: "YOUR_FANVUE_CLIENT_ID"
  client_secret: "YOUR_FANVUE_CLIENT_SECRET"
  redirect_uri: "http://localhost:8080/callback"

matrix:
  homeserver: "https://matrix.org"
  user_id: "@your_bot:matrix.org"
  access_token: "YOUR_MATRIX_ACCESS_TOKEN"

rooms:
  "#fanvue-subscribers:matrix.org":
    type: "subscription"
    active_subscription: true
    on_expiry: "kick"  # or "ignore"

  "#fanvue-vip:matrix.org":
    type: "spending"
    min_lifetime_spend_cents: 10000  # $100

  "#fanvue-whales:matrix.org":
    type: "spending"
    min_lifetime_spend_cents: 50000  # $500

  "#fanvue-top-spenders:matrix.org":
    type: "top_spender"

  "#fanvue-exclusive-content:matrix.org":
    type: "unlock"
    content_id: "uuid-of-the-content"
```

### Rule Types

| Type | Description | Parameters |
|------|-------------|------------|
| `subscription` | Active Fanvue subscribers | `active_subscription: true` |
| `spending` | Users who spent above a threshold | `min_lifetime_spend_cents` |
| `top_spender` | Users with Fanvue's top spender badge | None |
| `unlock` | Users who unlocked specific content | `content_id` |
| `fanvue_list` | Members of a Fanvue list | `list_uuid`, `list_type` (custom/smart) |

### Expiry Policies

| Policy | Discord | Matrix |
|--------|---------|--------|
| `remove_role` | Removes the role | N/A |
| `kick` | Kicks from server | Kicks from room |
| `ignore` | Keeps role (grandfather) | Keeps in room |

## Address Book

Both tools use an address book file to map Fanvue user UUIDs to platform-specific IDs (Discord user IDs or Matrix MXIDs). The file is stored as `discord_addressbook.yaml` or `addressbook.yaml` respectively.

Format:
```yaml
fanvue-uuid-1:
  - "@user:matrix.org"
fanvue-uuid-2:
  - "123456789012345678"  # Discord user ID
```

Users must be added to the address book for sync to work. With Discord OAuth enabled, users can self-link their accounts via the OAuth flow.

## Discord Auto-Join Setup

To enable automatic guild joining (like Patreon/Gumroad sync bots):

1. Create a Discord application at https://discord.com/developers/applications
2. Enable OAuth2 and add the redirect URI (e.g., `http://yourdomain.com:8080/callback`)
3. Note your OAuth2 Client ID and Client Secret
4. Ensure your bot has the `MANAGE_GUILD` permission in your server
5. Add the OAuth configuration to your `config.yaml`

Users can link their Discord accounts by visiting `http://yourdomain.com:8080/link?fanvue_uuid=THEIR_UUID`. After authorizing, they will be automatically added to your Discord server when they have an active Fanvue membership.

## Bidirectional List Sync

The list sync feature allows you to keep a Fanvue custom list and a Discord role in sync:

**Fanvue as Primary**: Members of the Fanvue list automatically receive the Discord role. When removed from the list, the role is removed.

**Discord as Primary**: Members with the Discord role are automatically added to the Fanvue custom list. When the role is removed, they are removed from the list. This requires Discord OAuth to be configured for user ID mapping.

## Architecture

```
fanvue-sync/
├── fanvue_common/           # Shared library
│   └── fanvue_common/
│       ├── client.py        # Fanvue API client with OAuth & rate limiting
│       ├── sync.py          # SyncEngine - computes room/role membership
│       ├── store.py         # SQLite store for transaction history
│       └── utils.py         # AddressBook for UUID <-> platform ID mapping
├── fanvue-discord-sync/     # Discord bot
│   └── fanvue_discord_sync/
│       ├── main.py          # Entry point
│       ├── bot.py           # Discord.py bot with role sync & upsell
│       └── offer_store.py   # Tracks sent upsell offers
└── fanvue-matrix-sync/      # Matrix bot
    └── fanvue_matrix_sync/
        ├── main.py          # Entry point
        └── bot.py           # matrix-nio bot with room enforcement
```

## How It Works

The sync process fetches all subscribers and followers from the Fanvue API, then evaluates each user against the configured rules. For spending-based rules, it queries individual fan insights. For content unlock rules, it maintains a local SQLite database of purchase transactions synced from the earnings API.

The Discord bot runs continuously, syncing roles every 5 minutes and listening for entitlement/boost events for upselling. The Matrix bot runs once per invocation (suitable for cron) and supports a `--dry-run` flag.

## Rate Limiting

The Fanvue API allows 100 requests per 60 seconds. The client automatically handles 429 responses and proactively pauses when the rate limit bucket runs low.

## Things to Keep in Mind and Intentionally Omitted Features

Fanvue rules forbid facilitation of on-platform in a manner that evade platform fees. For this reason, never offer a 100% off Fanvue subscription in exchange of a Discord boost or a Discord Creator SKU. Similarly, never offer 100% off Fanvue subscriptions in exchange for paying to register a Matrix homeserver. Partial discounts or VIP lists are usually okay, as they still encourage the member to spend in the Fanvue side. For the same reason, we didn't offer such a feature natively. 

When granting access to an age-restricted channel on Discord for a role or a NSFW room on Matrix side or granting access to a privileged DM list on Fanvue side, it's the member's responsibility to ensure they are not connecting their account with someone else's.

DMs are intentionally not bridged across platforms, as platform policies are significantly different and it could've caused moderation headaches. Neither Matrix or Discord have a concept of pay-to-unlock DMs, either; this project wouldn't have existed if either had that concept.

Anything sent to a federated Matrix room (including 1:1 chats) cannot reliably be withdrawn and assume that side of content may spread unmoderated.
Anything sent to a Discord channel can easily be withdrawn, but can be captured in the meantime.
Anything sent to a Fanvue DM cannot easily be withdrawn, and assume that side of content may be read by platform staff at times.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! Please open an issue or pull request on GitHub.

## Resources

- [Fanvue API Documentation](https://api.fanvue.com/docs)
- [Fanvue Developer Portal](https://fanvue.com/developers/apps)
- [discord.py Documentation](https://discordpy.readthedocs.io/)
- [matrix-nio Documentation](https://matrix-nio.readthedocs.io/)
