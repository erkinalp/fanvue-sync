import asyncio
import argparse
import yaml
import logging
import sys
import os
from fanvue_common.client import FanvueClient
from fanvue_common.utils import AddressBook
from fanvue_common.sync import SyncEngine
from fanvue_matrix_sync.bot import FanvueBot

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Main")

async def main():
    parser = argparse.ArgumentParser(description="Fanvue to Matrix Sync")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually change anything")
    args = parser.parse_args()

    try:
        with open(args.config, 'r') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"Config file {args.config} not found.")
        sys.exit(1)

    client = FanvueClient(config)
    # Auth check (simple flow for CLI)
    if not client.access_token:
        if os.path.exists("fanvue_tokens.json"):
             import json
             with open("fanvue_tokens.json", 'r') as f:
                 client._update_tokens(json.load(f))
        else:
            print("Please visit the following URL to authorize:")
            print(client.get_auth_url())
            code = input("Enter the authorization code: ")
            client.exchange_code(code)
            # Save tokens
            import json
            with open("fanvue_tokens.json", 'w') as f:
                json.dump({
                    "access_token": client.access_token,
                    "refresh_token": client.refresh_token,
                    "expires_in": 3600 # Approx
                }, f)

    sync_engine = SyncEngine(client, config)
    address_book = AddressBook()
    bot = FanvueBot(config)

    try:
        # Pre-flight: Sync specific bot state
        await bot.sync_state()

        # 1. Compute who should be where
        logger.info("Computing room membership...")
        room_mapping = sync_engine.compute_room_membership()

        # 2. Map Fanvue UUIDs to Matrix IDs
        final_mapping = {}
        for room_alias, user_uuids in room_mapping.items():
            final_mapping[room_alias] = set()
            for uuid in user_uuids:
                mxids = address_book.get_mxids(uuid)
                if mxids:
                    for mxid in mxids:
                        final_mapping[room_alias].add(mxid)
                else:
                    logger.warning(f"User {uuid} has no known Matrix ID.")
                    # TODO: Implement a way to ask/invite users to link their accounts!
                    # For now, we skip.

        # 3. Enforce
        if args.dry_run:
            logger.info("DRY RUN: Would enforce the following:")
            for room, mxids in final_mapping.items():
                logger.info(f"Room {room}: {len(mxids)} members")
                logger.debug(f"{room} -> {mxids}")
        else:
            for room, mxids in final_mapping.items():
                logger.info(f"Enforcing room {room}...")
                await bot.enforce_room(room, mxids)

    finally:
        await bot.close()

if __name__ == "__main__":
    import os
    asyncio.run(main())
