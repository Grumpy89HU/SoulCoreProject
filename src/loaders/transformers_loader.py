import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from src.base_slot import BaseSlot

class TransformersSlot(BaseSlot):
    def load(self):
        self.logger.info(f"Hivatalos Transformers modell betöltése: {self.config['repo_id']}")
        
        # Automatikus letöltés és betöltés
        self.tokenizer = AutoTokenizer.from_pretrained(self.config['repo_id'])
        self.model = AutoModelForCausalLM.from_pretrained(
            self.config['repo_id'],
            device_map=f"cuda:{self.config.get('gpu_id', 0)}",
            torch_dtype=torch.bfloat16, # Gemma 3-hoz javasolt
            low_cpu_mem_usage=True
        )
        self.is_loaded = True

    def unload(self):
        self.model = None
        self.tokenizer = None
        torch.cuda.empty_cache()
        self.is_loaded = False

    def generate(self, prompt, params=None):
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        outputs = self.model.generate(**inputs, max_new_tokens=params.get('max_tokens', 200))
        return self.tokenizer.decode(outputs[0], skip_special_tokens=True).replace(prompt, "")
