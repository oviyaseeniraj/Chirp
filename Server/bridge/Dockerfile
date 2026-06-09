FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for psycopg2 build
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY subscriber.py .

CMD ["python", "-u", "subscriber.py"]
