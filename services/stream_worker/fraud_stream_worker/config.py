import os
class Settings:
    MQ_HOST = os.environ.get("MQ_HOST", "localhost")
    MODEL_API = os.environ.get("MODEL_API", "http://localhost:8001")
    RULES_API = os.environ.get("RULES_API", "http://localhost:8002")
    ALERT_THRESHOLD = float(os.environ.get("ALERT_THRESHOLD", "0.75"))
