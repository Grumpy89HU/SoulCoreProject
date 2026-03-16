import httpx
import logging
import asyncio
from typing import Optional, Dict, Any

class DiplomaticGateway:
    def __init__(self, config: Dict[str, Any]):
        self.logger = logging.getLogger("Gateway")
        self.config = config
        self.api_cfg = config.get("api", {})
        self.external_endpoints = self.api_cfg.get("external_peers", {})
        self.api_key = self.api_cfg.get("gateway_key", "") # Opcionális biztonsági kulcs
        
        # Alapértelmezett beállítások
        self.default_timeout = 45.0
        self.retry_count = 2

    async def consult_external_entity(self, entity_name: str, prompt: str, context: Optional[Dict] = None) -> Optional[str]:
        """
        Kapcsolatfelvétel külső entitással (pl. Origó).
        
        :param entity_name: A cél entitás azonosítója a configban.
        :param prompt: Az üzenet szövege.
        :param context: Opcionális plusz adatok (pl. chat_id, user_role).
        :return: Az entitás válasza vagy None hiba esetén.
        """
        url = self.external_endpoints.get(entity_name)
        if not url:
            self.logger.warning(f"🚫 Ismeretlen diplomáciai célpont: {entity_name}")
            return None

        # Protokoll csomag összeállítása
        payload = {
            "source": "SoulCore_Kope",
            "prompt": prompt,
            "context": context or {},
            "timestamp": asyncio.get_event_loop().time()
        }

        headers = {
            "Content-Type": "application/json",
            "X-Gateway-Key": self.api_key
        }

        self.logger.info(f"🌐 Diplomáciai kapcsolat kezdeményezése: {entity_name}...")

        for attempt in range(self.retry_count + 1):
            try:
                async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
                    response = await client.post(
                        url, 
                        json=payload, 
                        timeout=self.default_timeout
                    )
                    
                    if response.status_code == 200:
                        res_data = response.json()
                        self.logger.info(f"✅ Válasz érkezett: {entity_name}")
                        return res_data.get("response")
                    else:
                        self.logger.error(f"⚠️ {entity_name} válasza: {response.status_code}")
                        
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                if attempt < self.retry_count:
                    wait_time = (attempt + 1) * 2
                    self.logger.warning(f"⏳ {entity_name} nem elérhető, újrapóbálkozás {wait_time}s múlva...")
                    await asyncio.sleep(wait_time)
                else:
                    self.logger.error(f"❌ Kapcsolat megszakadt {entity_name} felé: {e}")
            except Exception as e:
                self.logger.error(f"🔥 Kritikus Gateway hiba ({entity_name}): {e}")
                break

        return None

    def add_peer(self, name: str, url: str):
        """Dinamikus külső végpont hozzáadása futásidőben."""
        self.external_endpoints[name] = url
        self.logger.info(f"📡 Új diplomáciai csatorna nyitva: {name} -> {url}")

    async def broadcast_status(self, message: str):
        """Üzenet küldése minden ismert külső félnek (pl. rendszerleálláskor)."""
        tasks = [self.consult_external_entity(peer, message) for peer in self.external_endpoints]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)