import sqlite3
import json
from datetime import datetime, timedelta
from core.logger import get_logger

class DBManager:
    def __init__(self, db_path="soulcore.db"):
        self.db_path = db_path
        self.log = get_logger("db_manager")
        self._init_db()

    def _execute(self, query, params=(), commit=False, fetch_all=False):
        """Központi SQL végrehajtó. Biztosítja a szálbiztos lezárást."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                if commit:
                    conn.commit()
                if fetch_all:
                    return cursor.fetchall()
                return cursor.fetchone()
        except Exception as e:
            self.log.error(f"SQL Hiba: {e} | Query: {query[:50]}...")
            return None

    def _init_db(self):
        """Minden tábla inicializálása - Origó központosított sémája."""
        tables = [
            # 1. RENDSZER BEÁLLÍTÁSOK
            "CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, description TEXT)",
            
            # 2. Ollama modellek listája
            """CREATE TABLE IF NOT EXISTS ollama_models (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag TEXT UNIQUE NOT NULL,
                size_bytes INTEGER,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # 3. Keresési gyorsítótár
            """CREATE TABLE IF NOT EXISTS search_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_hash TEXT UNIQUE NOT NULL,
                raw_query TEXT,
                results_json TEXT,
                expires_at DATETIME
            )""",

            # 4. RÖVIDTÁVÚ MEMÓRIA
            """CREATE TABLE IF NOT EXISTS short_term_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conv_id TEXT NOT NULL,
                model_origin TEXT NOT NULL,
                topic_tag TEXT,
                content TEXT NOT NULL,
                importance_score FLOAT DEFAULT 0.5,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # 5. HOSSZÚTÁVÚ MEMÓRIA (Tények)
            """CREATE TABLE IF NOT EXISTS long_term_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                predicate TEXT,
                object_detail TEXT,
                reliability_index FLOAT DEFAULT 1.0,
                source_conv_id TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""", 
            
            # 6. Belső monológok és "szívverés" napló
            """CREATE TABLE IF NOT EXISTS internal_thought_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_model TEXT,
                protocol_version TEXT,
                raw_content TEXT,
                priority_level INTEGER DEFAULT 0,
                vram_usage REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",
            
            # 7. Entitás-memória (emberek, IP-k, jelszavak)
            """CREATE TABLE IF NOT EXISTS entity_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT, 
                key_name TEXT UNIQUE,
                value TEXT,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # 8. Feladatütemező
            # database.py - A Feladatütemező módosítása
            """CREATE TABLE IF NOT EXISTS task_scheduler (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT,  -- <--- Ide kerül az OpenWebUI csevegés azonosítója
                task_description TEXT,
                priority INTEGER DEFAULT 1,
                status TEXT DEFAULT 'pending', 
                scheduled_for TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",
            
            # 9. Üzenetek naplózása és kézbesítése
            """CREATE TABLE IF NOT EXISTS message (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )"""
        ]

        for table_sql in tables:
            self._execute(table_sql, commit=True)

        # --- FREEDOM MODE FIX ---
        # Ellenőrizzük, hogy létezik-e a bejegyzés. Ha nem, beszúrjuk.
        existing = self.get_setting("freedom_mode")
        if existing is None:
            self._execute("""
                INSERT INTO system_settings (key, value, description) 
                VALUES ('freedom_mode', 'false', 'Global freedom mode: if true, AI remembers past sessions.')
            """, commit=True)
            self.log.info("Freedom Mode alapértelmezés (false) beállítva.")
        
        self.log.info("SoulCore adatbázis sémák ellenőrizve.")

    # --- KÉNYELMI FUNKCIÓK A TESZTELÉSHEZ ---

    def toggle_freedom_mode(self, state: bool):
        """Gyors kapcsoló a Freedom Mode-hoz (True/False)."""
        value = "true" if state else "false"
        self.set_setting("freedom_mode", value)
        self.log.info(f"Freedom Mode átkapcsolva: {value.upper()}")

    def is_freedom_enabled(self) -> bool:
        """Lekéri a Freedom Mode aktuális állapotát bulyanként."""
        val = self.get_setting("freedom_mode", "false")
        return val.lower() == "true"

    # --- RENDSZER BEÁLLÍTÁSOK (CONFIG) ---

    def get_setting(self, key, default=None):
        res = self._execute("SELECT value FROM system_settings WHERE key = ?", (key,))
        return res[0] if res else default

    def set_setting(self, key, value):
        return self._execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (key, str(value)), commit=True)

    # --- RÖVIDTÁVÚ MEMÓRIA (SHORT TERM) ---

    def add_short_term_note(self, conv_id, model_origin, topic_tag, content, importance=0.5):
        query = """
            INSERT INTO short_term_notes (conv_id, model_origin, topic_tag, content, importance_score)
            VALUES (?, ?, ?, ?, ?)
        """
        return self._execute(query, (conv_id, model_origin, topic_tag, content, importance), commit=True)

    def get_notes_by_model(self, model_name, limit=5):
        query = """
            SELECT topic_tag, content FROM short_term_notes 
            WHERE model_origin = ? 
            ORDER BY created_at DESC LIMIT ?
        """
        return self._execute(query, (model_name, limit), fetch_all=True)

    def get_notes_for_conversation(self, conv_id):
        query = "SELECT topic_tag, content FROM short_term_notes WHERE conv_id = ?"
        return self._execute(query, (conv_id,), fetch_all=True)

    def clear_short_term_memory(self, conv_id):
        return self._execute("DELETE FROM short_term_notes WHERE conv_id = ?", (conv_id,), commit=True)

    # --- HOSSZÚTÁVÚ MEMÓRIA (LONG TERM) ---

    def get_long_term_memories(self, subject=None):
        if subject:
            query = "SELECT subject, predicate, object_detail FROM long_term_memory WHERE subject LIKE ?"
            return self._execute(query, (f"%{subject}%",), fetch_all=True)
        return self._execute("SELECT subject, predicate, object_detail FROM long_term_memory", fetch_all=True)

    # --- ENTITÁS MEMÓRIA (A Scribe használja) ---

    def update_entity_memory(self, entity_type, key_name, value):
        query = """
            INSERT INTO entity_memory (entity_type, key_name, value, last_updated)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key_name) DO UPDATE SET 
                value = excluded.value,
                last_updated = CURRENT_TIMESTAMP
        """
        return self._execute(query, (entity_type, key_name, value), commit=True)

    def get_entity_value(self, key_name):
        res = self._execute("SELECT value FROM entity_memory WHERE key_name = ?", (key_name,))
        return res[0] if res else None

    # --- BELSŐ NAPLÓZÁS (THOUGHT LOGS) ---

    def add_detailed_log(self, model, protocol, content, priority=0, vram=0.0):
        query = """
            INSERT INTO internal_thought_logs (source_model, protocol_version, raw_content, priority_level, vram_usage) 
            VALUES (?, ?, ?, ?, ?)
        """
        return self._execute(query, (model, protocol, content, priority, vram), commit=True)

    # --- EGYÉB FUNKCIÓK ---

    def update_ollama_model(self, tag, size):
        query = "INSERT OR REPLACE INTO ollama_models (tag, size_bytes, last_seen) VALUES (?, ?, datetime('now'))"
        return self._execute(query, (tag, size), commit=True)

    def save_search_to_cache(self, query_hash, raw_query, results_json, hours=12):
        query = """
            INSERT OR REPLACE INTO search_cache (query_hash, raw_query, results_json, expires_at)
            VALUES (?, ?, ?, datetime('now', ?))
        """
        return self._execute(query, (query_hash, raw_query, results_json, f'+{hours} hours'), commit=True)

    def get_cached_search(self, query_hash):
        query = "SELECT results_json FROM search_cache WHERE query_hash = ? AND expires_at > datetime('now')"
        res = self._execute(query, (query_hash,))
        return json.loads(res[0]) if res else None
        
    def get_next_pending_task(self):
        #Lekéri a következő végrehajtandó feladatot a hozzá tartozó chat_id-val.
        query = """
            SELECT id, chat_id, task_description, priority 
            FROM task_scheduler 
            WHERE status = 'pending' 
            AND (scheduled_for <= datetime('now', 'localtime') OR scheduled_for IS NULL)
            ORDER BY priority DESC LIMIT 1
        """
        return self._execute(query)

    def update_task_status(self, task_id, status):
        """Feladat állapotának frissítése (running, completed, failed)."""
        return self._execute("UPDATE task_scheduler SET status = ? WHERE id = ?", (status, task_id), commit=True)

    def get_internal_summary(self, limit=10):
        """Összefoglalót készít a legutóbbi gondolatokból a belső monológ számára."""
        query = "SELECT raw_content FROM internal_thought_logs ORDER BY timestamp DESC LIMIT ?"
        results = self._execute(query, (limit,), fetch_all=True)
        # Ha vannak eredmények, összefűzzük őket egy szöveggé
        return "\n".join([r[0] for r in results]) if results else ""