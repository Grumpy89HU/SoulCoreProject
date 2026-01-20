import sqlite3
import json
import time
from datetime import datetime, timedelta
from core.logger import get_logger

log = get_logger("db_manager")

class DBManager:
    def __init__(self, db_path="soulcore.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        """Létrehozza a táblákat, ha nem léteznek (4NF + AI Kognitív rétegek)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Rendszerbeállítások
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

            # 2. Ollama Inventory & Szerepkörök
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ollama_models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tag TEXT UNIQUE NOT NULL,
                    size_bytes INTEGER,
                    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS model_assignments (
                    role TEXT PRIMARY KEY,
                    model_id INTEGER,
                    FOREIGN KEY (model_id) REFERENCES ollama_models(id)
                )
            """)

            # 3. Keresési Cache (12 órás lejárat)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_hash TEXT UNIQUE NOT NULL,
                    raw_query TEXT,
                    results_json TEXT,
                    expires_at DATETIME
                )
            """)

            # --- ÚJ: KOGNITÍV ARCHITEKTÚRA RÉTEGEI (A "Végtelen Könyvtár") ---

            # 4. RÖVIDTÁVÚ MEMÓRIA (A "Cetlik a falon")
            # Minden modell saját cetliket írhat egy adott beszélgetéshez.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS short_term_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conv_id TEXT NOT NULL,
                    model_origin TEXT NOT NULL,    -- Ki írta? (pl. gemma3_kope)
                    topic_tag TEXT,                -- A cetli "címe" (pl. #ferrari_motor)
                    content TEXT NOT NULL,          -- A végtelenített jegyzet tartalma
                    importance_score FLOAT DEFAULT 0.5,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 5. HOSSZÚTÁVÚ MEMÓRIA (A "Tudásbázis" - Tények és összefüggések)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS long_term_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT NOT NULL,          -- Alany (pl. Ferrari 458)
                    predicate TEXT,                 -- Tulajdonság (pl. turbó_hiba)
                    object_detail TEXT,             -- Részletes leírás (450LE, V12, stb.)
                    reliability_index FLOAT DEFAULT 1.0,
                    source_conv_id TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 6. FELADATOK (A "Proaktív Emlékeztető")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS proactive_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trigger_time DATETIME,
                    task_description TEXT,
                    priority INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'pending',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 7. PISZKOZAT / GONDOLATI LÁNC (Rejtett jegyzet a válasz előtt)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS thought_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_name TEXT,
                    logical_steps TEXT,             -- Az AI belső érvelése
                    self_correction TEXT,           -- Mit javított ki magán
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()
            log.info("Adatbázis inicializálva (soulcore.db) - Kognitív táblák aktívak.")

    # --- CONFIG KEZELÉS ---
    def set_config(self, key, value):
        with self._get_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (key, str(value)))
            conn.commit()

    def get_config(self, key, default=None):
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else default

    # --- CACHE LOGIKA ---
    def get_cached_search(self, query_hash):
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT results_json FROM search_cache WHERE query_hash = ? AND expires_at > ?",
                (query_hash, datetime.now())
            )
            row = cursor.fetchone()
            if row:
                log.info(f"Cache találat: {query_hash}")
                return json.loads(row[0])
        return None

    def save_search(self, query_hash, raw_query, results):
        expiry = datetime.now() + timedelta(hours=12)
        with self._get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO search_cache (query_hash, raw_query, results_json, expires_at) VALUES (?, ?, ?, ?)",
                (query_hash, raw_query, json.dumps(results), expiry)
            )
            conn.commit()

    # --- ÚJ: JEGYZET KEZELŐ METÓDUSOK ---
    def add_short_term_note(self, conv_id, model, topic, content, importance=0.5):
        """Egy új 'cetli' felragasztása a falra."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO short_term_notes (conv_id, model_origin, topic_tag, content, importance_score)
                VALUES (?, ?, ?, ?, ?)
            """, (conv_id, model, topic, content, importance))
            conn.commit()
            log.info(f"Új jegyzet rögzítve: {topic} ({model})")

    def get_notes_for_model(self, conv_id, model):
        """Lekéri az összes cetlit, amit az adott modell írt az adott beszélgetésben."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT topic_tag, content FROM short_term_notes WHERE conv_id = ? AND model_origin = ?",
                (conv_id, model)
            )
            return cursor.fetchall()