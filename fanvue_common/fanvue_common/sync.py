import logging
from collections import defaultdict

from fanvue_common.store import TransactionStore

class SyncEngine:
    def __init__(self, client, config):
        self.client = client
        self.config = config
        self.logger = logging.getLogger("FanvueSync")
        self.store = TransactionStore()
        
        # Cache for user insights to avoid rate limits/duplicate calls
        self._user_cache = {}

    def _get_user_insights(self, user_uuid):
        if user_uuid not in self._user_cache:
            try:
                self._user_cache[user_uuid] = self.client.get_fan_insights(user_uuid)
            except Exception as e:
                self.logger.error(f"Failed to fetch insights for {user_uuid}: {e}")
                self._user_cache[user_uuid] = None
        return self._user_cache[user_uuid]
        
    def _sync_transactions(self):
        """Update local transaction store from API"""
        self.store.sync_earnings(self.client)

    def _get_user_total_spend(self, user_uuid):
        insights = self._get_user_insights(user_uuid)
        if not insights:
            return 0
        return insights.get('spending', {}).get('total', {}).get('gross', 0)

    def compute_room_membership(self):
        """
        Returns a dictionary: { room_alias: [set of user_uuids] }
        """
        # Ensure we have latest transaction data
        self._sync_transactions()
        
        mapping = defaultdict(set)
        
        # 1. Fetch all Subscribers
        self.logger.info("Fetching subscribers...")
        subscribers = list(self.client.get_subscribers())
        subscriber_uuids = {s['uuid'] for s in subscribers}
        
        # 2. Fetch Followers (potential VIPs)
        self.logger.info("Fetching followers...")
        followers = list(self.client.get_followers())
        
        # Combine all known users to check logic against
        # We process subscribers first, then followers who aren't subscribers
        all_users = subscribers + [f for f in followers if f['uuid'] not in subscriber_uuids]
        
        # 3. Iterate over Rules
        for room_alias, rules_config in self.config.get('rooms', {}).items():
            
            # Normalize config to a list of rules
            # Case A: {"rules": [ ... ], "on_expiry": ...}
            if isinstance(rules_config, dict) and 'rules' in rules_config:
                rules_list = rules_config['rules']
            # Case B: [Rule1, Rule2]
            elif isinstance(rules_config, list):
                rules_list = rules_config
            # Case C: Single Rule Dict
            else:
                rules_list = [rules_config]

            for rules in rules_list:
                rule_type = rules.get('type')
            
            if rule_type == 'subscription':
                # Basic subscription check
                if rules.get('active_subscription'):
                    for sub in subscribers:
                        mapping[room_alias].add(sub['uuid'])
            
            elif rule_type == 'spending':
                min_spend = rules.get('min_lifetime_spend_cents', 0)
                # We need to check spending for ALL users (subs + followers)
                # This could be slow if there are thousands of followers.
                # Optimization: Only check this if we have a reason to (e.g. they are in local cache)
                # For now, we iterate everyone.
                for user in all_users:
                    uuid = user['uuid']
                    # Optimization: Maybe the user listing has 'isTopSpender' flag?
                    # Fanvue API response for subscribers/followers has 'isTopSpender'.
                    # If we only care about top spenders, we could use that.
                    # But for precise amounts, we need insights.
                    
                    spend = self._get_user_total_spend(uuid)
                    if spend >= min_spend:
                        mapping[room_alias].add(uuid)

            elif rule_type == 'top_spender':
                # Check for isTopSpender flag
                for user in all_users:
                    if user.get('isTopSpender'):
                        mapping[room_alias].add(user['uuid'])
                        
            elif rule_type == 'unlock':
                # Content unlock check
                content_id = rules.get('content_id')
                if content_id:
                    # Specific unlockers from local store (efficient!)
                    unlockers = self.store.get_unlockers(content_id)
                    for uuid in unlockers:
                        mapping[room_alias].add(uuid)
                        
        return mapping
