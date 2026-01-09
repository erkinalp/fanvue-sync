import sqlite3
import datetime
import logging

class TransactionStore:
    def __init__(self, db_path='transactions.db'):
        self.db_path = db_path
        self._init_db()
        self.logger = logging.getLogger("TransactionStore")

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        # Table for purchases
        c.execute('''
            CREATE TABLE IF NOT EXISTS purchases (
                post_uuid TEXT,
                user_uuid TEXT,
                purchase_date TEXT,
                PRIMARY KEY (post_uuid, user_uuid)
            )
        ''')
        # Table for sync state
        c.execute('''
            CREATE TABLE IF NOT EXISTS sync_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_sync_date TEXT
            )
        ''')
        # Initialize sync state if empty
        c.execute('INSERT OR IGNORE INTO sync_state (id, last_sync_date) VALUES (1, NULL)')
        conn.commit()
        conn.close()

    def get_last_sync_date(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT last_sync_date FROM sync_state WHERE id = 1')
        row = c.fetchone()
        conn.close()
        return row[0] if row else None

    def update_last_sync_date(self, date_str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('UPDATE sync_state SET last_sync_date = ? WHERE id = 1', (date_str,))
        conn.commit()
        conn.close()

    def add_purchase(self, post_uuid, user_uuid, date_str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('INSERT OR IGNORE INTO purchases (post_uuid, user_uuid, purchase_date) VALUES (?, ?, ?)',
                      (post_uuid, user_uuid, date_str))
            conn.commit()
        except sqlite3.Error as e:
            self.logger.error(f"Database error: {e}")
        finally:
            conn.close()

    def get_unlockers(self, post_uuid):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT user_uuid FROM purchases WHERE post_uuid = ?', (post_uuid,))
        rows = c.fetchall()
        conn.close()
        return {row[0] for row in rows}

    def sync_earnings(self, client):
        last_sync = self.get_last_sync_date()
        self.logger.info(f"Syncing earnings since {last_sync or 'start'}...")
        
        # We process transaction streams. We need to find the LATEST date seen to update our cursor.
        max_date = last_sync
        
        count = 0
        try:
            for transaction in client.get_earnings(start_date=last_sync, sources=['post']):
                # Extract Data
                # 'Purchase Received' webhook schema says postUuid is top level.
                post_uuid = transaction.get('postUuid')
                if not post_uuid:
                    continue

                user = transaction.get('user') or transaction.get('sender')
                if not user or 'uuid' not in user:
                    continue
                
                user_uuid = user['uuid']
                date_str = transaction.get('date') # ISO string from API
                
                if date_str:
                    # Update max_date if this one is newer
                    # ISO strings sort lexically so invalid comparison works mostly, but let's be safe later if needed.
                    if not max_date or date_str > max_date:
                        max_date = date_str

                self.add_purchase(post_uuid, user_uuid, date_str)
                count += 1
                
            if max_date and max_date != last_sync:
                self.update_last_sync_date(max_date)
                
            self.logger.info(f"Synced {count} new purchase transactions.")
            
        except Exception as e:
            self.logger.error(f"Failed to sync earnings: {e}")
