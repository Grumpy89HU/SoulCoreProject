import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

class Reranker:
    def __init__(self, config):
        self.mode = config.get("mode", "local")
        self.model_name = config.get("model_name", "Qwen/Qwen3-Reranker-0.6B")
        self.device = config.get("device", "cuda") if torch.cuda.is_available() else "cpu"
        
        if self.mode == "local":
            print(f"--- Reranker: Modell betöltése ({self.device}): {self.model_name} ---")
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            
            from transformers import AutoConfig
            config = AutoConfig.from_pretrained(self.model_name, trust_remote_code=True)
            
            
            # FONTOS: trust_remote_code=True és a megfelelő architektúra kényszerítése
            # Megpróbáljuk kényszeríteni az architektúrát
            self.model = AutoModelForSequenceClassification.from_pretrained(
                self.model_name,
                config=config,
                dtype=torch.float16 if self.device == "cuda" else torch.float32,
                trust_remote_code=True,
                device_map=self.device
            )
            self.model.eval()

    def get_local_score(self, query, passage):
        if self.mode != "local":
            return 0.0
            
        with torch.no_grad():
            inputs = self.tokenizer(
                query, 
                passage, 
                return_tensors='pt', 
                padding=True, 
                truncation=True, 
                max_length=512
            ).to(self.device)
            
            outputs = self.model(**inputs)
            
            # Mivel 2 elemet kaptunk, megnézzük a logits dimenzióját
            logits = outputs.logits[0] 
            
            if logits.dim() > 0 and len(logits) > 1:
                # Ha 2 elemű (Softmax/Cross-Entropy), a második elem a relevancia (index 1)
                # Alkalmazunk egy Softmax-ot, hogy valószínűséget kapjunk
                probs = torch.softmax(logits, dim=0)
                score = probs[1].cpu().item() 
            else:
                # Ha csak 1 elemű (Sigmoid), marad az eredeti
                score = torch.sigmoid(logits).cpu().item()
                
            return score