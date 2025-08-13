FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY fraud_rules_api ./fraud_rules_api
CMD ["uvicorn", "fraud_rules_api.app:app", "--host", "0.0.0.0", "--port", "8002"]
