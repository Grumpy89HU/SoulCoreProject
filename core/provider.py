import httpx
import json

class LLMProvider:
    def __init__(self, base_url: str, default_model: str):
        self.base_url = base_url.rstrip('/')
        self.default_model = default_model

    async def generate_response(self, prompt: str, system_prompt: str = "", temp: float = 0.7, model_override: str = None):
        target_model = model_override or self.default_model
        
        # Gemma-Native formátum a System prompt kényszerítésére
        formatted_prompt = (
            f"<start_of_turn>system\n{system_prompt}<end_of_turn>\n"
            f"<start_of_turn>user\n{prompt}<end_of_turn>\n"
            f"<start_of_turn>model\n"
        )
        
        payload = {
            "model": target_model,
            "prompt": formatted_prompt,
            "stream": False,
            "options": {
                "temperature": temp,
                "stop": ["<end_of_turn>", "user:", "Asszisztens:"]
            }
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                url = f"{self.base_url}/api/generate"
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                return data.get('response', 'Üres válasz érkezett.')
            except Exception as e:
                return f"Hiba az Ollama elérésekor ({target_model}): {str(e)}"

    async def generate_embedding(self, text: str, model: str = "qwen3-embedding:4b"):
        """Ez a hiányzó láncszem a memóriához"""
        payload = {
            "model": model,
            "prompt": text
        }
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                url = f"{self.base_url}/api/embeddings"
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                # Az Ollama az 'embedding' kulcs alatt adja vissza a listát
                return data.get('embedding')
            except Exception as e:
                print(f"Embedding hiba: {str(e)}")
                return None