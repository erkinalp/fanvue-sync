import sqlite3
import logging

class OfferStore:
    def __init__(self, db_path='offers.db'):
        self.db_path = db_path
        self._init_db()
        self.logger = logging.getLogger("OfferStore")

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS sent_offers (
                user_id TEXT PRIMARY KEY,
                entitlement_id TEXT,
                sent_at TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def has_received_offer(self, user_id, entitlement_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT 1 FROM sent_offers WHERE user_id = ? AND entitlement_id = ?', (str(user_id), str(entitlement_id)))
        row = c.fetchone()
        conn.close()
        return row is not None

    def record_offer(self, user_id, entitlement_id):
        import datetime
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('INSERT INTO sent_offers (user_id, entitlement_id, sent_at) VALUES (?, ?, ?)',
                      (str(user_id), str(entitlement_id), datetime.datetime.now().isoformat()))
            conn.commit()
        except sqlite3.Error as e:
            self.logger.error(f"Database error: {e}")
        finally:
            conn.close()
