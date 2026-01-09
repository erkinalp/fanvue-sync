import discord
import logging
import asyncio
from fanvue_common.utils import AddressBook
from .offer_store import OfferStore

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
            await asyncio.sleep(300) # Sync every 5 minutes OR use a configured interval
