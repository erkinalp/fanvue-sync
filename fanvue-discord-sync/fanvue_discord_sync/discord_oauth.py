import os
import base64
import time
import sqlite3
import logging
import requests
import aiohttp
from urllib.parse import urlencode

class DiscordOAuthClient:
    """Discord OAuth2 client for user authentication with guilds.join scope."""
    
    DISCORD_API_BASE = "https://discord.com/api/v10"
    DISCORD_AUTH_BASE = "https://discord.com/oauth2"
    
    def __init__(self, config, db_path='discord_oauth.db'):
        self.client_id = config['discord']['oauth_client_id']
        self.client_secret = config['discord']['oauth_client_secret']
        self.redirect_uri = config['discord']['oauth_redirect_uri']
        self.bot_token = config['discord']['token']
        self.guild_id = config['discord']['guild_id']
        self.db_path = db_path
        self.logger = logging.getLogger("DiscordOAuth")
        self._session = None
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS discord_tokens (
                fanvue_uuid TEXT PRIMARY KEY,
                discord_user_id TEXT NOT NULL,
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                token_expiry INTEGER,
                created_at TEXT,
                updated_at TEXT
            )
        ''')
        c.execute('''
            CREATE INDEX IF NOT EXISTS idx_discord_user_id 
            ON discord_tokens(discord_user_id)
        ''')
        conn.commit()
        conn.close()
    
    def _generate_state(self, fanvue_uuid):
        """Generate a secure state parameter that encodes the Fanvue UUID."""
        random_bytes = os.urandom(16)
        state_data = f"{fanvue_uuid}:{base64.urlsafe_b64encode(random_bytes).decode()}"
        return base64.urlsafe_b64encode(state_data.encode()).decode()
    
    def _decode_state(self, state):
        """Decode the state parameter to extract Fanvue UUID."""
        try:
            decoded = base64.urlsafe_b64decode(state.encode()).decode()
            fanvue_uuid = decoded.split(':')[0]
            return fanvue_uuid
        except Exception:
            return None
    
    def get_auth_url(self, fanvue_uuid):
        """Generate Discord OAuth URL with guilds.join scope."""
        state = self._generate_state(fanvue_uuid)
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "identify guilds.join",
            "state": state,
        }
        return f"{self.DISCORD_AUTH_BASE}/authorize?{urlencode(params)}", state
    
    def exchange_code(self, code, state):
        """Exchange authorization code for tokens."""
        fanvue_uuid = self._decode_state(state)
        if not fanvue_uuid:
            raise ValueError("Invalid state parameter")
        
        data = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        
        response = requests.post(
            f"{self.DISCORD_AUTH_BASE}/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        response.raise_for_status()
        token_data = response.json()
        
        discord_user = self._get_user_info(token_data['access_token'])
        discord_user_id = discord_user['id']
        
        self._store_tokens(
            fanvue_uuid=fanvue_uuid,
            discord_user_id=discord_user_id,
            access_token=token_data['access_token'],
            refresh_token=token_data.get('refresh_token'),
            expires_in=token_data.get('expires_in', 604800)
        )
        
        return fanvue_uuid, discord_user_id, token_data
    
    def _get_user_info(self, access_token):
        """Get Discord user info using their access token."""
        response = requests.get(
            f"{self.DISCORD_API_BASE}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        response.raise_for_status()
        return response.json()
    
    def _store_tokens(self, fanvue_uuid, discord_user_id, access_token, refresh_token, expires_in):
        """Store Discord OAuth tokens in database."""
        import datetime
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        now = datetime.datetime.now().isoformat()
        token_expiry = int(time.time()) + expires_in
        
        c.execute('''
            INSERT OR REPLACE INTO discord_tokens 
            (fanvue_uuid, discord_user_id, access_token, refresh_token, token_expiry, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM discord_tokens WHERE fanvue_uuid = ?), ?), ?)
        ''', (fanvue_uuid, discord_user_id, access_token, refresh_token, token_expiry, fanvue_uuid, now, now))
        conn.commit()
        conn.close()
    
    def get_user_token(self, fanvue_uuid):
        """Get stored Discord token for a Fanvue user."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            SELECT discord_user_id, access_token, refresh_token, token_expiry 
            FROM discord_tokens WHERE fanvue_uuid = ?
        ''', (fanvue_uuid,))
        row = c.fetchone()
        conn.close()
        
        if not row:
            return None
        
        discord_user_id, access_token, refresh_token, token_expiry = row
        
        if time.time() > token_expiry - 60:
            access_token = self._refresh_user_token(fanvue_uuid, refresh_token)
        
        return {
            'discord_user_id': discord_user_id,
            'access_token': access_token
        }
    
    def _refresh_user_token(self, fanvue_uuid, refresh_token):
        """Refresh a user's Discord access token."""
        if not refresh_token:
            raise Exception("No refresh token available")
        
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
        }
        
        response = requests.post(
            f"{self.DISCORD_AUTH_BASE}/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        response.raise_for_status()
        token_data = response.json()
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            SELECT discord_user_id FROM discord_tokens WHERE fanvue_uuid = ?
        ''', (fanvue_uuid,))
        row = c.fetchone()
        conn.close()
        
        if row:
            self._store_tokens(
                fanvue_uuid=fanvue_uuid,
                discord_user_id=row[0],
                access_token=token_data['access_token'],
                refresh_token=token_data.get('refresh_token', refresh_token),
                expires_in=token_data.get('expires_in', 604800)
            )
        
        return token_data['access_token']
    
    def get_discord_id_for_fanvue(self, fanvue_uuid):
        """Get Discord user ID for a Fanvue UUID."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT discord_user_id FROM discord_tokens WHERE fanvue_uuid = ?', (fanvue_uuid,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else None
    
    def get_fanvue_id_for_discord(self, discord_user_id):
        """Get Fanvue UUID for a Discord user ID."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT fanvue_uuid FROM discord_tokens WHERE discord_user_id = ?', (str(discord_user_id),))
        row = c.fetchone()
        conn.close()
        return row[0] if row else None
    
    def get_all_linked_users(self):
        """Get all linked Fanvue-Discord user pairs."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT fanvue_uuid, discord_user_id FROM discord_tokens')
        rows = c.fetchall()
        conn.close()
        return {row[0]: row[1] for row in rows}
    
    async def _get_session(self):
        """Get or create a reusable aiohttp ClientSession."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self):
        """Close the aiohttp session. Call this when done with the client."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    async def add_user_to_guild(self, fanvue_uuid, roles=None):
        """
        Add a user to the guild using their OAuth token.
        This requires the guilds.join scope and bot with CREATE_INSTANT_INVITE permission.
        
        Args:
            fanvue_uuid: The Fanvue user UUID
            roles: Optional list of role IDs to assign on join
            
        Returns:
            True if user was added, False if already in guild, raises on error
        """
        token_info = self.get_user_token(fanvue_uuid)
        if not token_info:
            self.logger.warning(f"No Discord token for Fanvue user {fanvue_uuid}")
            return False
        
        discord_user_id = token_info['discord_user_id']
        user_access_token = token_info['access_token']
        
        url = f"{self.DISCORD_API_BASE}/guilds/{self.guild_id}/members/{discord_user_id}"
        
        payload = {
            "access_token": user_access_token
        }
        if roles:
            payload["roles"] = [str(r) for r in roles]
        
        session = await self._get_session()
        async with session.put(
            url,
            json=payload,
            headers={"Authorization": f"Bot {self.bot_token}"}
        ) as response:
            if response.status == 201:
                self.logger.info(f"Added user {discord_user_id} to guild {self.guild_id}")
                return True
            elif response.status == 204:
                self.logger.info(f"User {discord_user_id} already in guild {self.guild_id}")
                return False
            else:
                response.raise_for_status()
