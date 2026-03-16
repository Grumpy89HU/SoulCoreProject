import sqlite3
import json
import uuid
import os
import logging
from datetime import datetime
from qdrant_client import QdrantClient
from qdrant_client.http import models
import networkx as nx
from sentence_transformers import SentenceTransformer, CrossEncoder
from passlib.context import CryptContext

class SoulCoreDatabase:
    def __init__(self, db_path="vault/db/soulcore.db"):
        self.logger = logging.getLogger("Database")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        
        self.vector_path = "vault/db/soul_vectors"
        self.graph_path = "vault/db/social_graph.json"
        
        # Jelszókezelő a biztonságos belépéshez
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        
        self._init_sqlite()
        
        # Kezdeti adatok betöltése, ha üres az adatbázis
        if not self.get_config("project"):
            self._seed_initial_data()
        
        self.rag_cfg = self.get_config("rag_system")
        self.storage_cfg = self.get_config("storage")

        # 1. VEKTOROS MOTOR (Qdrant)
        self.client = None
        try:
            print(f"🧬 Szuverén Embedding betöltése: {self.rag_cfg['embedding']['local_path']}")
            self.embedding_model = SentenceTransformer(self.rag_cfg['embedding']['local_path'])
            self.client = QdrantClient(path=self.vector_path)
            self._init_vector_collections()
        except Exception as e:
            self.logger.error(f"Vektoros motor hiba az inicializáláskor: {e}")

        # 2. RERANKER
        self.reranker = None
        if self.rag_cfg.get('reranker', {}).get('enabled'):
            print(f"🔍 Szuverén Reranker aktív.")
            try:
                self.reranker = CrossEncoder(self.rag_cfg['reranker']['local_path'])
            except Exception as e:
                self.logger.error(f"Reranker hiba: {e}")

        # 3. GRÁF MEMÓRIA
        self.graph_db = self._load_graph()
        print(f"🏛️ SoulCore 2.0: SQL + RAG + Graph élesítve.")

    def _init_sqlite(self):
        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            c.execute('CREATE TABLE IF NOT EXISTS system_config (key TEXT PRIMARY KEY, value TEXT)')
            c.execute('''CREATE TABLE IF NOT EXISTS slots (
                name TEXT PRIMARY KEY, enabled INTEGER, role TEXT, engine TEXT, 
                model_name TEXT, filename TEXT, gpu_id INTEGER, max_vram_mb INTEGER, 
                n_ctx INTEGER, temperature REAL, model_path TEXT)''')
            
            # AUTH tábla a webes belépéshez
            c.execute('CREATE TABLE IF NOT EXISTS auth (username TEXT PRIMARY KEY, password_hash TEXT, role TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, username TEXT, role TEXT)')
            
            c.execute('''CREATE TABLE IF NOT EXISTS chats (
                chat_id TEXT PRIMARY KEY, user_id TEXT, title TEXT, 
                created_at TEXT, last_active TEXT)''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, role TEXT, 
                content TEXT, debug_data TEXT, timestamp TEXT)''')
            
            c.execute('''CREATE TABLE IF NOT EXISTS long_memory (
                key TEXT PRIMARY KEY, content TEXT, metadata TEXT, timestamp TEXT)''')
            conn.commit()

    # --- KONFIGURÁCIÓ KEZELÉS ---
    def get_config(self, key):
        try:
            with sqlite3.connect(self.db_path) as conn:
                res = conn.execute("SELECT value FROM system_config WHERE key = ?", (key,)).fetchone()
                if res:
                    try:
                        return json.loads(res[0])
                    except (json.JSONDecodeError, TypeError):
                        return res[0]
                return None
        except Exception as e:
            self.logger.error(f"Config olvasási hiba ({key}): {e}")
            return None

    def set_config(self, key, value):
        with sqlite3.connect(self.db_path) as conn:
            val_to_save = json.dumps(value) if isinstance(value, (dict, list)) else json.dumps(value)
            conn.execute("INSERT OR REPLACE INTO system_config VALUES (?, ?)", (key, val_to_save))
            conn.commit()

    def get_full_config(self):
        return {
            "project": self.get_config("project") or {},
            "api": self.get_config("api") or {},
            "hardware": self.get_config("hardware") or {},
            "storage": self.get_config("storage") or {},
            "rag_system": self.get_config("rag_system") or {}
        }

    # --- SLOT / MODELL KEZELÉS ---
    def save_slot(self, name, data):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''INSERT OR REPLACE INTO slots VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (name, data.get('enabled', 0), data.get('role'), data.get('engine'), 
                 data.get('model_name'), data.get('filename'), data.get('gpu_id', 0), 
                 data.get('max_vram_mb', 0), data.get('n_ctx', 2048), 
                 data.get('temperature', 0.7), data.get('model_path')))
            conn.commit()

    def get_enabled_slots(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return {row['name']: dict(row) for row in conn.execute("SELECT * FROM slots WHERE enabled = 1").fetchall()}

    def get_sovereign_identity(self):
        project = self.get_config("project") or {}
        return {
            "name": project.get("identity", "Kópé"),
            "traits": project.get("character_traits", "Intelligens, szuverén, segítőkész."),
            "codename": project.get("codename", "Esernyő")
        }

    # --- RAG / VEKTOROS FUNKCIÓK ---
    def _init_vector_collections(self):
        if not self.client: return
        try:
            collections = self.client.get_collections().collections
            if not any(c.name == "soul_vectors" for c in collections):
                dim = self.rag_cfg['embedding']['vector_dimension']
                self.client.create_collection(
                    collection_name="soul_vectors",
                    vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE)
                )
        except Exception as e: self.logger.error(f"Vektor kollekció hiba: {e}")

    def query_vault(self, query_text, user_id=None, limit=None):
        try:
            if not self.client: return ""
            limit = limit or self.rag_cfg['context']['max_chunks_per_query']
            prefix = self.rag_cfg['embedding']['instruction_type']['query']
            vector = self.embedding_model.encode(f"{prefix}{query_text}").tolist()
            
            filt = models.Filter(must=[models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id))]) if user_id else None
            
            response = self.client.query_points(
                collection_name="soul_vectors",
                query=vector,
                limit=limit,
                query_filter=filt
            )
            
            if not response or not response.points: return ""
            passages = [res.payload.get("text", "") for res in response.points]
            
            if self.reranker and len(passages) > 1:
                scores = self.reranker.predict([[query_text, p] for p in passages])
                ranked = sorted(zip(scores, passages), key=lambda x: x[0], reverse=True)
                return " | ".join([p for s, p in ranked if s >= self.rag_cfg['reranker']['relevance_threshold']][:self.rag_cfg['reranker']['top_n']])
            
            return " | ".join(passages[:5])
        except Exception as e: 
            self.logger.error(f"Vault query hiba: {e}")
            return ""

    def save_to_vault(self, text, user_id="Grumpy", chat_id="default"):
        if not self.client: return
        try:
            prefix = self.rag_cfg['embedding']['instruction_type']['document']
            vector = self.embedding_model.encode(f"{prefix}{text}").tolist()
            self.client.upsert(
                collection_name="soul_vectors",
                points=[models.PointStruct(id=int(datetime.now().timestamp()*1000), vector=vector, payload={
                    "user_id": user_id, "chat_id": chat_id, "text": text, "timestamp": datetime.now().isoformat()
                })]
            )
        except Exception as e:
            self.logger.error(f"Vault mentési hiba: {e}")

    # --- CHAT ÉS ÜZENET KEZELÉS ---
    def save_message(self, chat_id, role, content, debug=None, user_id="Grumpy"):
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            try:
                debug_val = json.dumps(debug, ensure_ascii=False) if debug is not None else None
            except:
                debug_val = str(debug)

            conn.execute("INSERT INTO messages (chat_id, role, content, debug_data, timestamp) VALUES (?, ?, ?, ?, ?)",
                         (chat_id, role, content, debug_val, now))
            
            res = conn.execute("SELECT chat_id FROM chats WHERE chat_id = ?", (chat_id,)).fetchone()
            if not res:
                title = (content[:30] + '...') if len(content) > 30 else content
                conn.execute("INSERT INTO chats (chat_id, user_id, title, created_at, last_active) VALUES (?, ?, ?, ?, ?)",
                             (chat_id, user_id, title, now, now))
            else:
                conn.execute("UPDATE chats SET last_active = ? WHERE chat_id = ?", (now, chat_id))
            conn.commit()

    def get_chat_history(self, chat_id, limit=20):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            res = conn.execute("SELECT role, content, timestamp FROM messages WHERE chat_id = ? ORDER BY timestamp DESC LIMIT ?", 
                               (chat_id, limit)).fetchall()
            return list(reversed([dict(row) for row in res]))

    def get_all_chat_sessions(self, user_id=None):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if user_id:
                res = conn.execute("SELECT chat_id, title, last_active FROM chats WHERE user_id = ? ORDER BY last_active DESC", (user_id,)).fetchall()
            else:
                res = conn.execute("SELECT chat_id, title, last_active FROM chats ORDER BY last_active DESC").fetchall()
            return [dict(row) for row in res]

    def update_chat_title(self, chat_id, title):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE chats SET title = ? WHERE chat_id = ?", (title, chat_id))
            conn.commit()

    # --- HOSSZÚ TÁVÚ MEMÓRIA ---
    def set_long_memory(self, key, text, metadata=""):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO long_memory (key, content, metadata, timestamp) VALUES (?, ?, ?, ?)", 
                         (key, text, metadata, datetime.now().isoformat()))
            conn.commit()

    def get_all_long_memory(self):
        with sqlite3.connect(self.db_path) as conn:
            res = conn.execute("SELECT content FROM long_memory ORDER BY timestamp DESC").fetchall()
            if not res: return "No long-term memories stored yet."
            return "\n".join([row[0] for row in res])

    def save_to_long_memory(self, content, metadata=""):
        with sqlite3.connect(self.db_path) as conn:
            key = str(uuid.uuid4())[:8]
            conn.execute(
                "INSERT INTO long_memory (key, content, metadata, timestamp) VALUES (?, ?, ?, ?)",
                (key, content, metadata, datetime.now().isoformat())
            )
            conn.commit()
            return key

    # --- AUTH / BIZTONSÁG ---
    def verify_user(self, username, password):
        try:
            with sqlite3.connect(self.db_path) as conn:
                res = conn.execute("SELECT password_hash FROM auth WHERE username = ?", (username,)).fetchone()
                if res and self.pwd_context.verify(password, res[0]):
                    return True
        except Exception as e:
            self.logger.error(f"Auth hiba: {e}")
        return False

    def create_user(self, username, password, role="user"):
        hashed = self.pwd_context.hash(password)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO auth VALUES (?, ?, ?)", (username, hashed, role))
            conn.execute("INSERT OR REPLACE INTO users VALUES (?, ?, ?)", (username, username, role))
            conn.commit()

    # --- GRÁF ÉS SEEDING ---
    def _load_graph(self):
        if os.path.exists(self.graph_path):
            try:
                with open(self.graph_path, 'r', encoding='utf-8') as f:
                    return nx.node_link_graph(json.load(f))
            except Exception: return nx.MultiDiGraph()
        return nx.MultiDiGraph()

    def _seed_initial_data(self):
        print("🌱 Teljes SoulCore rendszer-migráció az adatbázisba...")
        self.set_config("project", {
            "name": "SoulCore", "version": "2.0", "identity": "Kópé", "codename": "",
            "character_traits": "Intelligens, szuverén, néha csípős humorú partner.",
            "user_lang": "hu", "internal_lang": "en"
        })
        self.set_config("api", {"host": "0.0.0.0", "port": 8000, "cors": ["*"], "timeout": 60})
        self.set_config("hardware", {"gpu_count": 2, "total_vram_limit_mb": 32768, "cuda_devices": ["cuda:0", "cuda:1"], "primary_gpu": 0})
        self.set_config("storage", {"model_root": "./models", "vault_root": "./vault", "db_limit_gb": 1500})
        
        self.set_config("rag_system", {
            "enabled": True,
            "embedding": {
                "local_path": "/mnt/raid/soulcore/SoulCore2.0/models/ragsystem/embeddinggemma",
                "vector_dimension": 768, "instruction_type": {"query": "query: ", "document": "passage: "}
            },
            "context": {"window_size": 131072, "chunk_size": 4096, "max_chunks_per_query": 15},
            "reranker": {"enabled": False, "local_path": "/mnt/raid/soulcore/SoulCore2.0/models/reranker/qwen3vlreranker2B", "top_n": 5, "relevance_threshold": 0.65}
        })

        slots = {
            "translator": {"enabled": 1, "role": "Translator", "engine": "gguf", "model_name": "Translategemma-4b", "filename": "translategemma-4b-it-Q4_K_M.gguf", "gpu_id": 1, "max_vram_mb": 2500, "n_ctx": 1024, "temperature": 0.1, "model_path": "./models"},
            "scribe": {"enabled": 1, "role": "Gatekeeper", "engine": "gguf", "model_name": "NuExtract-v1.5", "filename": "NuExtract-v1.5-Q3_K_XL.gguf", "gpu_id": 1, "max_vram_mb": 3000, "n_ctx": 2048, "temperature": 0.0, "model_path": "./models"},
            "valet": {"enabled": 1, "role": "Logistics", "engine": "gguf", "model_name": "Qwen2.5 1.5B", "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf", "gpu_id": 1, "max_vram_mb": 4000, "n_ctx": 2048, "temperature": 0.4, "model_path": "./models"},
            "king": {"enabled": 1, "role": "Sovereign", "engine": "gguf", "model_name": "Gemma3 27B", "filename": "Gemma3_27B_uncensored-Q3_K_M.gguf", "gpu_id": 0, "max_vram_mb": 0, "n_ctx": 2048, "temperature": 0.8, "model_path": "./models"}
        }
        for name, data in slots.items():
            self.save_slot(name, data)

        # Grumpy alapértelmezett admin létrehozása
        self.create_user("Grumpy", "soulcore_admin", role="admin")

    def close(self):
        if hasattr(self, 'client') and self.client: 
            try:
                self.client.close()
            except Exception as e:
                self.logger.error(f"Kliens lezárási hiba: {e}")