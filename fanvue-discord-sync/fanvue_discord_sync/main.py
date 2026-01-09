import asyncio
import argparse
import yaml
import logging
import sys
import os
from fanvue_common.client import FanvueClient
from fanvue_common.utils import AddressBook
from fanvue_common.sync import SyncEngine
from fanvue_discord_sync.bot import DiscordBot

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DiscordMain")

def main():
    parser = argparse.ArgumentParser(description="Fanvue to Discord Sync")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    args = parser.parse_args()

    try:
        with open(args.config, 'r') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"Config file {args.config} not found.")
        sys.exit(1)

    # Transform 'roles' config to 'rooms' format expected by SyncEngine
    # SyncEngine expects config['rooms']. We have config['roles'].
    # We can just key it as 'rooms' or pass a modified config.
    sync_config = config.copy()
    if 'roles' in config:
        sync_config['rooms'] = config['roles']
    
    client = FanvueClient(config)
    # Auth check (Same as Matrix bot, maybe abstract this later)
    if not client.access_token:
        # Try loading from shared token file (default location in Client)
        if os.path.exists("fanvue_tokens.json"):
             import json
             with open("fanvue_tokens.json", 'r') as f:
                 client._update_tokens(json.load(f))
        else:
            print("Please visit the following URL to authorize:")
            print(client.get_auth_url())
            code = input("Enter the authorization code: ")
            client.exchange_code(code)
            import json
            with open("fanvue_tokens.json", 'w') as f:
                json.dump({
                    "access_token": client.access_token,
                    "refresh_token": client.refresh_token,
                    "expires_in": 3600 # Approx
                }, f)

    sync_engine = SyncEngine(client, sync_config)
    bot = DiscordBot(config, sync_engine)

    try:
        bot.run(config['discord']['token'])
    except Exception as e:
        logger.error(f"Bot failed: {e}")

if __name__ == "__main__":
    main()
