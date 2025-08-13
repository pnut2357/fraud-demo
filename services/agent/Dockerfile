FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY fraud_agent ./fraud_agent
CMD ["python", "fraud_agent/agent.py"]
