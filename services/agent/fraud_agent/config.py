import os
class Settings:
    MQ_HOST = os.environ.get("MQ_HOST", "localhost")
    DB_PATH = os.environ.get("DB_PATH", "/data/fraud.db")
    POLICY_PATH = os.environ.get("POLICY_PATH", "/app/config/decision_policy.json")
    OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434/api/chat")
    AGENT_MODEL = os.environ.get("AGENT_MODEL", "llama3.1:8b")
    FALLBACK_ENABLE = os.environ.get("FALLBACK_ENABLE", "true").lower() == "true"
