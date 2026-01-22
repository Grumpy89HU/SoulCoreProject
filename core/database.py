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
        """Központi SQL végrehajtó. Csak itt érünk hozzá a sqlite3-hoz."""
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
            # Rendszer beállítások
            "CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
            
            # Ollama modellek listája
            """CREATE TABLE IF NOT EXISTS ollama_models (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag TEXT UNIQUE NOT NULL,
                size_bytes INTEGER,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # Keresési gyorsítótár
            """CREATE TABLE IF NOT EXISTS search_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_hash TEXT UNIQUE NOT NULL,
                raw_query TEXT,
                results_json TEXT,
                expires_at DATETIME
            )""",

            # RÖVIDTÁVÚ MEMÓRIA (Ez válaszolt neked a szalonnáról!)
            """CREATE TABLE IF NOT EXISTS short_term_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conv_id TEXT NOT NULL,
                model_origin TEXT NOT NULL,
                topic_tag TEXT,
                content TEXT NOT NULL,
                importance_score FLOAT DEFAULT 0.5,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""",

            # HOSSZÚTÁVÚ MEMÓRIA (Tények, amik sosem évülnek el)
            """CREATE TABLE IF NOT EXISTS long_term_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                predicate TEXT,
                object_detail TEXT,
                reliability_index FLOAT DEFAULT 1.0,
                source_conv_id TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""", 
            
            # Belső monológok és "szívverés" napló
            """CREATE TABLE IF NOT EXISTS internal_thought_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_model TEXT,
                protocol_version TEXT,
                raw_content TEXT,
                priority_level INTEGER DEFAULT 0,
                vram_usage REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );""",
            
            # Rövid távú entitás-memória (emberek, IP-k, jelszavak, helyszínek)
            """CREATE TABLE IF NOT EXISTS entity_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT, 
                key_name TEXT UNIQUE,
                value TEXT,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
            );"""
        ]
        
        for table_cmd in tables:
            self._execute(table_cmd, commit=True)
            
        self.log.info("SoulCore Adatbázis (DAL) minden táblája aktív.")

    # --- PUBLIKUS METÓDUSOK (Ezeket hívja a Kernel és a többi modul) ---

    def set_config(self, key, value):
        query = "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)"
        return self._execute(query, (key, str(value)), commit=True)

    def get_config(self, key, default=None):
        query = "SELECT value FROM system_settings WHERE key = ?"
        res = self._execute(query, (key,))
        return res[0] if res else default

    def add_short_term_note(self, conv_id, model_origin, topic_tag, content, importance=0.5):
        query = """
            INSERT INTO short_term_notes (conv_id, model_origin, topic_tag, content, importance_score)
            VALUES (?, ?, ?, ?, ?)
        """
        self._execute(query, (conv_id, model_origin, topic_tag, content, importance), commit=True)
        self.log.info(f"Jegyzet rögzítve: {topic_tag}")

    def get_notes_for_model(self, conv_id, model_origin):
        query = "SELECT topic_tag, content FROM short_term_notes WHERE conv_id = ? AND model_origin = ?"
        return self._execute(query, (conv_id, model_origin), fetch_all=True)

    def delete_note_by_id(self, note_id):
        """Példa: törlés megvalósítása."""
        query = "DELETE FROM short_term_notes WHERE id = ?"
        return self._execute(query, (note_id,), commit=True)

    def clear_short_term_memory(self, conv_id):
        """Mindent töröl egy adott beszélgetéshez."""
        query = "DELETE FROM short_term_notes WHERE conv_id = ?"
        return self._execute(query, (conv_id,), commit=True)
    
    def update_ollama_model(self, tag, size):
        """Ollama modellek frissítése kívülről érkező SQL nélkül."""
        query = """
            INSERT OR REPLACE INTO ollama_models (tag, size_bytes, last_seen)
            VALUES (?, ?, datetime('now'))
        """
        return self._execute(query, (tag, size), commit=True)
        
    # --- SEARCH CACHE MŰVELETEK ---

    def get_cached_search(self, query_hash):
        """Keresési cache lekérése (SQL bezárva)."""
        query = "SELECT results_json FROM search_cache WHERE query_hash = ? AND expires_at > datetime('now')"
        res = self._execute(query, (query_hash,))
        if res:
            return json.loads(res[0])
        return None

    def save_search_to_cache(self, query_hash, raw_query, results_json, hours=12):
        """Keresési eredmény mentése a cache-be."""
        query = """
            INSERT OR REPLACE INTO search_cache (query_hash, raw_query, results_json, expires_at)
            VALUES (?, ?, ?, datetime('now', ?))
        """
        return self._execute(query, (query_hash, raw_query, results_json, f'+{hours} hours'), commit=True)
    
    def get_notes_for_conversation(self, conv_id):
        """
        Kizárólag az adott beszélgetéshez tartozó jegyzeteket adja vissza.
        Így az új beszélgetés (új conv_id) tiszta lappal indul.
        """
        query = "SELECT topic_tag, content FROM short_term_notes WHERE conv_id = ?"
        # Itt nem szűrünk modellre, mert minden 'al-én' láthatja a közös jegyzetet az adott szálon
        return self._execute(query, (conv_id,), fetch_all=True)

    def get_long_term_memories(self, subject=None):
        """
        Hosszútávú tények lekérése, amik minden beszélgetésnél relevánsak lehetnek.
        """
        if subject:
            query = "SELECT subject, predicate, object_detail FROM long_term_memory WHERE subject LIKE ?"
            return self._execute(query, (f"%{subject}%",), fetch_all=True)
        else:
            query = "SELECT subject, predicate, object_detail FROM long_term_memory"
            return self._execute(query, fetch_all=True)
            
    def setup_soul_core_tables(self):
        """Létrehozza a Vár mélyebb adatszerkezetét a központi végrehajtón keresztül."""
        queries = [
            # Belső monológok és "szívverés" napló
            """CREATE TABLE IF NOT EXISTS internal_thought_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_model TEXT,
                protocol_version TEXT,
                raw_content TEXT,
                priority_level INTEGER DEFAULT 0,
                vram_usage REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            );""",
            
            # Rövid távú entitás-memória (emberek, IP-k, jelszavak, helyszínek)
            """CREATE TABLE IF NOT EXISTS entity_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT, 
                key_name TEXT UNIQUE,
                value TEXT,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
            );"""
        ]
        for q in queries:
            self._execute(q, commit=True) # Itt a self._execute-ot használjuk!
        self.log.info("SoulCore extra modulok (Internal Logs, Entity Memory) inicializálva.")

    def add_detailed_log(self, model, protocol, content, priority, vram):
        """Részletes belső naplózás a Heartbeat és az Írnok számára."""
        query = """INSERT INTO internal_thought_logs 
                   (source_model, protocol_version, raw_content, priority_level, vram_usage) 
                   VALUES (?, ?, ?, ?, ?)"""
        return self._execute(query, (model, protocol, content, priority, vram), commit=True)