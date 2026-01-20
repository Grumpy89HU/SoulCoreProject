import mysql.connector
import yaml

class DatabaseManager:
    def __init__(self, config_path: str):
        with open(config_path, "r") as f:
            self.cfg = yaml.safe_load(f)
        
        # A config.yaml-ba tedd bele a mysql szekciót!
        db_cfg = self.cfg.get("database", {})
        
        self.db = mysql.connector.connect(
            host=db_cfg.get("host", "localhost"),
            user=db_cfg.get("user", "root"),
            password=db_cfg.get("password", ""),
            database=db_cfg.get("name", "lelek")
        )
        self.cursor = self.db.cursor(dictionary=True)
        self._setup_tables()

    def _setup_tables(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS search_cache (
                id INT AUTO_INCREMENT PRIMARY KEY,
                query VARCHAR(255) UNIQUE,
                result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.commit()

    def get_cached_search(self, query):
        self.cursor.execute("SELECT result FROM search_cache WHERE query = %s", (query,))
        return self.cursor.fetchone()

    def save_search(self, query, result):
        try:
            self.cursor.execute("INSERT INTO search_cache (query, result) VALUES (%s, %s)", (query, result))
            self.db.commit()
        except:
            pass # Ha már létezik, nem mentjük újra
