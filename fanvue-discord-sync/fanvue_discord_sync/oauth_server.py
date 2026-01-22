import logging
import asyncio
from aiohttp import web

class OAuthCallbackServer:
    """Simple web server to handle Discord OAuth callbacks."""
    
    def __init__(self, config, discord_oauth, address_book=None):
        self.config = config
        self.discord_oauth = discord_oauth
        self.address_book = address_book
        self.logger = logging.getLogger("OAuthServer")
        self.app = web.Application()
        self.app.router.add_get('/callback', self.handle_callback)
        self.app.router.add_get('/link', self.handle_link_request)
        self.runner = None
    
    async def handle_link_request(self, request):
        """Generate a Discord OAuth link for a Fanvue user."""
        fanvue_uuid = request.query.get('fanvue_uuid')
        if not fanvue_uuid:
            return web.Response(
                text="Missing fanvue_uuid parameter",
                status=400
            )
        
        auth_url, state = self.discord_oauth.get_auth_url(fanvue_uuid)
        
        return web.Response(
            text=f'<html><body>'
                 f'<h1>Link Your Discord Account</h1>'
                 f'<p>Click the button below to link your Discord account to your Fanvue membership.</p>'
                 f'<a href="{auth_url}" style="display:inline-block;padding:10px 20px;'
                 f'background:#5865F2;color:white;text-decoration:none;border-radius:5px;">'
                 f'Connect Discord</a>'
                 f'</body></html>',
            content_type='text/html'
        )
    
    async def handle_callback(self, request):
        """Handle Discord OAuth callback."""
        code = request.query.get('code')
        state = request.query.get('state')
        error = request.query.get('error')
        
        if error:
            self.logger.error(f"OAuth error: {error}")
            return web.Response(
                text=f"Authorization failed: {error}",
                status=400
            )
        
        if not code or not state:
            return web.Response(
                text="Missing code or state parameter",
                status=400
            )
        
        try:
            fanvue_uuid, discord_user_id, token_data = self.discord_oauth.exchange_code(code, state)
            
            if self.address_book:
                self.address_book.add(fanvue_uuid, str(discord_user_id))
            
            self.logger.info(f"Successfully linked Fanvue {fanvue_uuid} to Discord {discord_user_id}")
            
            return web.Response(
                text='<html><body>'
                     '<h1>Success!</h1>'
                     '<p>Your Discord account has been linked to your Fanvue membership.</p>'
                     '<p>You will be automatically added to the server if you have an active membership.</p>'
                     '</body></html>',
                content_type='text/html'
            )
            
        except Exception as e:
            self.logger.error(f"OAuth exchange failed: {e}")
            return web.Response(
                text=f"Authorization failed: {str(e)}",
                status=500
            )
    
    async def start(self, host='0.0.0.0', port=8080):
        """Start the OAuth callback server."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, host, port)
        await site.start()
        self.logger.info(f"OAuth callback server started on {host}:{port}")
    
    async def stop(self):
        """Stop the OAuth callback server."""
        if self.runner:
            await self.runner.cleanup()
            self.logger.info("OAuth callback server stopped")


async def run_oauth_server(config, discord_oauth, address_book=None, host='0.0.0.0', port=8080):
    """Run the OAuth callback server as a standalone coroutine."""
    server = OAuthCallbackServer(config, discord_oauth, address_book)
    await server.start(host, port)
    
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        await server.stop()
