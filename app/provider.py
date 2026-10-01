import json
import os
import re
import httpx
from .extraction import Extraction, SYSTEM_PROMPT

class ProviderError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__("Provider request failed")

class GeminiProvider:
    def __init__(self, key=None, model=None, transport=None):
        self.key = key or os.environ.get("GEMINI_API_KEY")
        self.model = model or os.environ.get("GENERATION_MODEL")
        if not self.key or not self.model:
            raise RuntimeError("Set GEMINI_API_KEY and GENERATION_MODEL")
        if not re.fullmatch(r"[a-zA-Z0-9._-]+", self.model):
            raise ValueError("Invalid model name")
        self.transport = transport

    def extract(self, source, theme, event_at):
        return self.generate(Extraction, SYSTEM_PROMPT, {"selected_theme":theme,"event_at":event_at.isoformat() if event_at else None,"source":source})

    def generate(self, schema, system, content):
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": json.dumps(content, ensure_ascii=False)}]}],
            "generationConfig": {"responseMimeType":"application/json", "responseJsonSchema":schema.model_json_schema(), "temperature":0.1}
        }
        with httpx.Client(timeout=120, transport=self.transport) as client:
            response = client.post(f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent", headers={"x-goog-api-key":self.key}, json=payload)
        if response.status_code != 200:
            # Never put provider body or credentials in stored job errors.
            raise ProviderError(f"gemini_http_{response.status_code}")
        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates or candidates[0].get("finishReason") != "STOP":
            raise ProviderError("gemini_incomplete_output")
        output = "".join(part.get("text", "") for part in candidates[0].get("content", {}).get("parts", []) if not part.get("thought"))
        return schema.model_validate_json(output)
