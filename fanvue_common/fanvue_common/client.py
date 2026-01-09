import requests
import hashlib
import os
import base64
import time
from urllib.parse import urlencode

class FanvueClient:
    API_BASE = "https://api.fanvue.com"
    AUTH_BASE = "https://auth.fanvue.com/oauth2"
    
    def __init__(self, config):
        self.client_id = config['fanvue']['client_id']
        self.client_secret = config['fanvue']['client_secret']
        self.redirect_uri = config['fanvue']['redirect_uri']
        self.access_token = None
        self.refresh_token = None
        self.token_expiry = 0
        
        # Load tokens from storage if available (simple implementation)
        self.token_file = "fanvue_tokens.json"
        
    def _generate_pkce(self):
        code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode('utf-8')
        m = hashlib.sha256()
        m.update(code_verifier.encode('utf-8'))
        code_challenge = base64.urlsafe_b64encode(m.digest()).rstrip(b'=').decode('utf-8')
        return code_verifier, code_challenge

    def get_auth_url(self):
        self.code_verifier, code_challenge = self._generate_pkce()
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid offline_access read:fan read:insights",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": base64.urlsafe_b64encode(os.urandom(16)).decode('utf-8')
        }
        return f"{self.AUTH_BASE}/auth?{urlencode(params)}"

    def exchange_code(self, code):
        data = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": self.code_verifier
        }
        response = requests.post(f"{self.AUTH_BASE}/token", data=data)
        response.raise_for_status()
        self._update_tokens(response.json())

    def _update_tokens(self, token_data):
        self.access_token = token_data['access_token']
        self.refresh_token = token_data.get('refresh_token')
        self.token_expiry = time.time() + token_data.get('expires_in', 3600)

    def _refresh_token(self):
        if not self.refresh_token:
            raise Exception("No refresh token available")
            
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token
        }
        response = requests.post(f"{self.AUTH_BASE}/token", data=data)
        response.raise_for_status()
        self._update_tokens(response.json())

    def _get_headers(self):
        if time.time() > self.token_expiry - 60:
            self._refresh_token()
        return {
            "Authorization": f"Bearer {self.access_token}",
            "X-Fanvue-API-Version": "2025-06-26"
        }

    def _request(self, method, endpoint, **kwargs):
        """
        Internal request wrapper with rate limit handling.
        """
        url = f"{self.API_BASE}{endpoint}"
        
        # Add auth headers automatically if not submitting to auth endpoint
        if "auth.fanvue.com" not in url:
             if "headers" not in kwargs:
                 kwargs["headers"] = {}
             kwargs["headers"].update(self._get_headers())

        while True:
            response = requests.request(method, url, **kwargs)
            
            # Check for Rate Limits
            try:
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 5))
                    print(f"Rate limited! Waiting {retry_after} seconds...")
                    time.sleep(retry_after + 1)
                    continue
                
                # Proactive rate limiting check (optional, but good for token buckets)
                remaining = response.headers.get("X-RateLimit-Remaining")
                if remaining is not None and int(remaining) < 5:
                     # If we approach 0, we want to wait for reset to stay well below the limit
                     reset_time = int(response.headers.get("X-RateLimit-Reset", 0))
                     wait_time = max(0, reset_time - time.time())
                     if wait_time > 0:
                         print(f"Rate limit bucket low (<5). Pausing for {wait_time:.1f}s...")
                         time.sleep(wait_time + 1)
                         
            except (ValueError, TypeError):
                pass
                
            return response

    def get_subscribers(self):
        """Yields all active subscribers"""
        page = 1
        while True:
            params = {"page": page, "size": 50}
            response = self._request("GET", "/subscribers", params=params)
            response.raise_for_status()
            data = response.json()
            
            for subscriber in data['data']:
                yield subscriber
                
            if not data['pagination']['hasMore']:
                break
            page += 1

    def get_followers(self):
        """Yields all followers (who are not subscribers)"""
        page = 1
        while True:
            params = {"page": page, "size": 50}
            response = self._request("GET", "/followers", params=params)
            response.raise_for_status()
            data = response.json()
            
            for follower in data['data']:
                yield follower
                
            if not data['pagination']['hasMore']:
                break
            page += 1

    def get_fan_insights(self, fan_uuid):
        """Get spending and status insights for a fan"""
        response = self._request("GET", f"/insights/fans/{fan_uuid}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    # get_post_unlockers removed in favor of SyncEngine + TransactionStore implementation


    def get_earnings(self, start_date=None, sources=None):
        """Yields earning transactions"""
        page_cursor = None
        while True:
            params = {"size": 50}
            if page_cursor:
                params['cursor'] = page_cursor
            if start_date:
                params['startDate'] = start_date
            if sources:
                params['source'] = ",".join(sources)
                
            response = self._request("GET", "/insights/earnings", params=params)
            response.raise_for_status()
            data = response.json()
            
            for item in data['data']:
                yield item
                
            page_cursor = data.get('nextCursor')
            if not page_cursor:
                break
