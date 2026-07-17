# Minimal ARM64-compatible MLflow server image built from the project lock so
# the tracking server version always matches the client.
FROM python:3.12-slim
RUN groupadd --gid 10002 mlflow \
    && useradd --uid 10002 --gid 10002 --create-home --shell /usr/sbin/nologin mlflow
COPY requirements/lock.txt /tmp/lock.txt
# Install only what the server needs from the lock (mlflow + drivers).
RUN pip install --no-cache-dir \
    "$(grep -E '^mlflow==' /tmp/lock.txt)" \
    psycopg2-binary boto3 \
    && rm /tmp/lock.txt
USER 10002:10002
EXPOSE 5000
