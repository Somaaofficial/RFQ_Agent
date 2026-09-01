FROM python:3.11-slim

# System deps needed by PyMuPDF / pandas wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 10000

CMD ["gunicorn", "-w", "1", "-t", "300", "-b", "0.0.0.0:10000", "rfq_agent.api:app"]
