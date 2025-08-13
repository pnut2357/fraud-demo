FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY fraud_model_api ./fraud_model_api
CMD ["uvicorn", "fraud_model_api.app:app", "--host", "0.0.0.0", "--port", "8001"]
