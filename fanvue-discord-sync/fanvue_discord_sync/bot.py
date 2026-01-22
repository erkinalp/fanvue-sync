import discord
import logging
import asyncio
from fanvue_common.utils import AddressBook
from .offer_store import OfferStore
from .discord_oauth import DiscordOAuthClient

class DiscordBot(discord.Client):
    def __init__(self, config, sync_engine):
        intents = discord.Intents.default()
        intents.members = True # Required to list members and roles
        super().__init__(intents=intents)
        
        self.config = config
        self.sync_engine = sync_engine
        self.address_book = AddressBook("discord_addressbook.yaml")
        self.offer_store = OfferStore()
        self.guild_id = config['discord']['guild_id']
        self.logger = logging.getLogger("DiscordBot")
        
        # Initialize Discord OAuth client if configured
        self.discord_oauth = None
        if config.get('discord', {}).get('oauth_client_id'):
            self.discord_oauth = DiscordOAuthClient(config)

    async def on_ready(self):
        self.logger.info(f'Logged in as {self.user} (ID: {self.user.id})')
        
        # Start the sync loop
        self.bg_task = self.loop.create_task(self.sync_loop())

    async def on_entitlement_create(self, entitlement):
        """Triggered when a user buys a subscription/product"""
        await self.check_upsell(entitlement.user_id, entitlement.sku_id)

    async def on_member_update(self, before, after):
        """Triggered when a member updates (roles, nickname, boost status, etc.)"""
        # Check for Server Boost
        # premium_since is None if not boosting, and a datetime if boosting.
        if self.config.get('upsell', {}).get('upsell_on_boost', False):
            if before.premium_since is None and after.premium_since is not None:
                self.logger.info(f"User {after.name} started boosting!")
                # We use a virtual SKU ID for boosts
                await self.check_upsell(after.id, "SERVER_BOOST")

    async def check_upsell(self, user_id, sku_id):
        required_skus = self.config.get('upsell', {}).get('required_entitlement_ids', [])
        
        # Check if SKU matches configuration OR is the virtual boost SKU
        is_boost = (str(sku_id) == "SERVER_BOOST")
        is_eligible_sku = (str(sku_id) in required_skus)
        
        if is_boost or is_eligible_sku:
            if not self.offer_store.has_received_offer(user_id, sku_id):
                user = await self.fetch_user(user_id)
                if user:
                    msg = self.config.get('upsell', {}).get('offer_message', "Thank you!")
                    try:
                        await user.send(msg)
                        self.logger.info(f"Sent upsell offer to {user_id}")
                        self.offer_store.record_offer(user_id, sku_id)
                    except discord.Forbidden:
                        self.logger.warning(f"Could not DM user {user_id}")

    async def sync_fanvue_roles(self):
        self.logger.info("Starting Fanvue -> Discord Sync")
        
        # 1. Compute Membership
        # Note: sync_engine.compute_room_membership returns { alias: [uuids] }
        # Here we interpret 'alias' as 'Role ID'.
        membership = self.sync_engine.compute_room_membership()
        
        guild = self.get_guild(self.guild_id)
        if not guild:
            self.logger.error("Guild not found!")
            return

        # 1.5. Auto-join users to guild if enabled
        if self.config.get('auto_join', {}).get('enabled', False):
            await self.auto_join_members_to_guild(membership)

        # 2. Iterate roles
        for role_id_str, fanvue_uuids in membership.items():
            try:
                role = guild.get_role(int(role_id_str))
                if not role:
                    self.logger.warning(f"Role {role_id_str} not found in guild.")
                    continue
                
                # Get Discord User IDs for these Fanvue UUIDs
                discord_ids = set()
                for uuid in fanvue_uuids:
                    # AddressBook: uuid -> [id1, id2] (supports multiple, mainly for mix)
                    # We assume AddressBook is shared or we have a discord-specific one.
                    # config example maps Fanvue UUID <-> Discord ID
                    ids = self.address_book.get_mxids(uuid) # Reusing get_mxids for generic IDs
                    if ids:
                        discord_ids.update(ids)

                # 3. Enforce Role
                # For members in guild, if they are in discord_ids, give role. Else remove.
                # Warning: iterating all members can be slow. iterating discord_ids is faster if small.
                
                # A better approach for large guilds:
                # 1. Get all members with the role -> set A
                # 2. Get all members who SHOULD have the role -> set B
                # 3. Add to (B - A). Remove from (A - B).
                
                current_members_with_role = {m.id for m in role.members}
                
                # We need to map discord_ids (str or int) to ints (64-bit Snowflakes)
                # Python handles large integers natively, so no precision loss here.
                target_ids = {int(x) for x in discord_ids}
                
                # 'Dismember' check: Verify who has the role but shouldn't (Fanvue entitlement lost)
                to_add = target_ids - current_members_with_role
                to_remove = current_members_with_role - target_ids
                
                for uid in to_add:
                    member = guild.get_member(uid)
                    if member:
                        await member.add_roles(role, reason="Fanvue Sync")
                        self.logger.info(f"Added role {role.name} to {member.name}")
                        await asyncio.sleep(1) # Pacing

                for uid in to_remove:
                    member = guild.get_member(uid)
                    if member:
                        # Check expiry policy for this role
                        role_config = self.config.get('roles', {}).get(role_id_str, {})
                        
                        # Resolve on_expiry depending on config format
                        if isinstance(role_config, dict):
                            action = role_config.get('on_expiry', 'remove_role')
                        elif isinstance(role_config, list):
                            # If it's a list, check the first item or assume default
                            # Ideally user should put 'on_expiry' in a top-level dict "rules: [...]"
                            # But for [Rule1, Rule2] compat, we default to remove_role or check item 0
                            action = role_config[0].get('on_expiry', 'remove_role') if role_config else 'remove_role'
                        else:
                            action = 'remove_role'
                        
                        if action == 'kick':
                            await member.kick(reason="Fanvue entitlement expired")
                            self.logger.info(f"Kicked {member.name} due to expired entitlement")
                        elif action == 'ignore':
                            self.logger.info(f"Ignoring expiry for {member.name} (grandfathered)")
                        else:
                            # Default: remove_role
                            await member.remove_roles(role, reason="Fanvue Sync expired")
                            self.logger.info(f"Removed role {role.name} from {member.name}")
                        
                        await asyncio.sleep(1) # Pacing
                        
            except Exception as e:
                self.logger.error(f"Error syncing role {role_id_str}: {e}")

    async def sync_loop(self):
        await self.wait_until_ready()
        while not self.is_closed():
            await self.sync_fanvue_roles()
            await self.sync_list_roles()
            await asyncio.sleep(300) # Sync every 5 minutes OR use a configured interval
    
    async def auto_join_members_to_guild(self, membership):
        """
        Auto-join users to the guild based on their Fanvue membership.
        Requires Discord OAuth with guilds.join scope.
        """
        if not self.discord_oauth:
            self.logger.warning("Discord OAuth not configured, skipping auto-join")
            return
        
        all_entitled_uuids = set()
        for fanvue_uuids in membership.values():
            all_entitled_uuids.update(fanvue_uuids)
        
        auto_join_roles = self.config.get('auto_join', {}).get('roles', [])
        
        for fanvue_uuid in all_entitled_uuids:
            try:
                result = await self.discord_oauth.add_user_to_guild(
                    fanvue_uuid, 
                    roles=auto_join_roles if auto_join_roles else None
                )
                if result:
                    self.logger.info(f"Auto-joined Fanvue user {fanvue_uuid} to guild")
                await asyncio.sleep(1)
            except Exception as e:
                self.logger.error(f"Failed to auto-join {fanvue_uuid}: {e}")
    
    async def sync_list_roles(self):
        """
        Sync between Fanvue lists and Discord roles based on configuration.
        Supports bidirectional sync with either side as primary.
        """
        list_sync_config = self.config.get('list_sync', {})
        if not list_sync_config:
            return
        
        guild = self.get_guild(self.guild_id)
        if not guild:
            return
        
        for sync_name, sync_config in list_sync_config.items():
            role_id = sync_config.get('discord_role_id')
            list_uuid = sync_config.get('fanvue_list_uuid')
            list_type = sync_config.get('fanvue_list_type', 'custom')
            primary = sync_config.get('primary', 'fanvue')
            
            if not role_id or not list_uuid:
                self.logger.warning(f"Incomplete list_sync config for {sync_name}")
                continue
            
            role = guild.get_role(int(role_id))
            if not role:
                self.logger.warning(f"Role {role_id} not found for list sync {sync_name}")
                continue
            
            try:
                if primary == 'fanvue':
                    await self._sync_fanvue_list_to_role(list_uuid, list_type, role, guild)
                elif primary == 'discord':
                    await self._sync_role_to_fanvue_list(role, list_uuid, guild)
                else:
                    self.logger.warning(f"Unknown primary '{primary}' for {sync_name}")
            except Exception as e:
                self.logger.error(f"Error in list sync {sync_name}: {e}")
    
    async def _sync_fanvue_list_to_role(self, list_uuid, list_type, role, guild):
        """Sync Fanvue list members to a Discord role (Fanvue as primary)."""
        list_members = self.sync_engine._get_list_members(list_uuid, list_type)
        
        target_discord_ids = set()
        for fanvue_uuid in list_members:
            if self.discord_oauth:
                discord_id = self.discord_oauth.get_discord_id_for_fanvue(fanvue_uuid)
            else:
                ids = self.address_book.get_mxids(fanvue_uuid)
                discord_id = next(iter(ids), None) if ids else None
            
            if discord_id:
                target_discord_ids.add(int(discord_id))
        
        current_members_with_role = {m.id for m in role.members}
        
        to_add = target_discord_ids - current_members_with_role
        to_remove = current_members_with_role - target_discord_ids
        
        for uid in to_add:
            member = guild.get_member(uid)
            if member:
                await member.add_roles(role, reason="Fanvue List Sync")
                self.logger.info(f"Added role {role.name} to {member.name} (list sync)")
                await asyncio.sleep(1)
        
        for uid in to_remove:
            member = guild.get_member(uid)
            if member:
                await member.remove_roles(role, reason="Fanvue List Sync")
                self.logger.info(f"Removed role {role.name} from {member.name} (list sync)")
                await asyncio.sleep(1)
    
    async def _sync_role_to_fanvue_list(self, role, list_uuid, guild):
        """Sync Discord role members to a Fanvue custom list (Discord as primary)."""
        if not self.discord_oauth:
            self.logger.warning("Discord OAuth required for Discord-primary list sync")
            return
        
        discord_member_ids = {m.id for m in role.members}
        self.sync_engine.sync_role_to_fanvue_list(
            list_uuid, 
            discord_member_ids, 
            self.discord_oauth
        )
