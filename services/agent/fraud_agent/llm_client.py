import requests, json

class OllamaClient:
    def __init__(self, url: str, model: str):
        self.url = url; self.model = model

    def chat(self, system_prompt: str, payload: dict) -> str:
        req = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload)}
            ],
            "stream": False,
            "options": {"temperature": 0.2}
        }
        r = requests.post(self.url, json=req, timeout=15)
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "").strip()
