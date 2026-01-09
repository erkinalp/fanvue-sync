import asyncio
import logging
import os
from nio import AsyncClient, AsyncClientConfig, RoomInviteError, RoomKickError, RoomResolveAliasResponse

class FanvueBot:
    def __init__(self, config):
        self.homeserver = config['matrix']['homeserver']
        self.user_id = config['matrix']['user_id']
        self.access_token = config['matrix']['access_token']
        self.config = config
        
        # Ensure store directory exists
        if not os.path.exists("store"):
            os.makedirs("store")
            
        self.client = AsyncClient(
            self.homeserver, 
            self.user_id, 
            store_path="store",
            config=AsyncClientConfig(
                max_limit_exceeded=0,
                max_timeouts=0,
                store_sync_tokens=True,
                encryption_enabled=True
            )
        )
        self.client.access_token = self.access_token
        self.logger = logging.getLogger("FanvueBot")

    async def sync_state(self):
        """Perform an initial sync to populate internal state"""
        self.logger.info("Syncing with Matrix (this may take a while)...")
        # Sync with a timeout helps updates propagate. 
        # For a CLI tool, we might want to sync until we are 'caught up' vaguely.
        # But a single sync call with full_state=True (on first run) or normal sync is needed.
        # If we have a token, it will be incremental.
        await self.client.sync(timeout=30000)
        self.logger.info("Sync complete.")

    async def resolve_room_alias(self, alias):
        resp = await self.client.room_resolve_alias(alias)
        if isinstance(resp, RoomResolveAliasResponse):
            return resp.room_id
        return None

    async def invite_user(self, room_id, mxid):
        try:
            await self.client.room_invite(room_id, mxid)
            self.logger.info(f"Invited {mxid} to {room_id}")
        except Exception as e:
            self.logger.error(f"Failed to invite {mxid} to {room_id}: {e}")

    async def kick_user(self, room_id, mxid, reason="Subscription expired"):
        try:
            await self.client.room_kick(room_id, mxid, reason=reason)
            self.logger.info(f"Kicked {mxid} from {room_id}")
        except Exception as e:
            self.logger.error(f"Failed to kick {mxid} from {room_id}: {e}")

    async def get_room_members(self, room_id):
        # Use cached state from the store
        if room_id in self.client.rooms:
            return list(self.client.rooms[room_id].users.keys())
        
        self.logger.warning(f"Room {room_id} not found in sync state. Attempting API fallback.")
        # Fallback to API if we haven't joined or synced yet
        resp = await self.client.joined_members(room_id)
        if hasattr(resp, 'members'):
            return [m.user_id for m in resp.members]
        return []

    async def enforce_room(self, room_alias, allowed_mxids):
        room_id = await self.resolve_room_alias(room_alias)
        if not room_id:
            self.logger.error(f"Could not resolve alias {room_alias}")
            return

        current_members = await self.get_room_members(room_id)
        current_members = set(current_members)
        allowed_mxids = set(allowed_mxids)
        
        # Don't kick the bot itself!
        current_members.discard(self.user_id)

        to_invite = allowed_mxids - current_members
        to_kick = current_members - allowed_mxids

        # Check expiry policy
        room_config = self.config.get('rooms', {}).get(room_alias, {})
        
        # Resolve on_expiry depending on config format
        if isinstance(room_config, dict):
            action = room_config.get('on_expiry', 'kick')
        elif isinstance(room_config, list):
            action = room_config[0].get('on_expiry', 'kick') if room_config else 'kick'
        else:
            action = 'kick'
        
        if action == 'ignore':
            if to_kick:
                self.logger.info(f"Ignoring expiry for {len(to_kick)} users in {room_alias} (grandfathered)")
            to_kick = set()

        for mxid in to_invite:
            await self.invite_user(room_id, mxid)
            await asyncio.sleep(1) # Pacing to avoid rate limits
            
        for mxid in to_kick:
            await self.kick_user(room_id, mxid)
            await asyncio.sleep(1) # Pacing to avoid rate limits

    async def close(self):
        await self.client.close()
