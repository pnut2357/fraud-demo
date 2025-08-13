FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY fraud_stream_worker ./fraud_stream_worker
CMD ["python", "fraud_stream_worker/worker.py"]
