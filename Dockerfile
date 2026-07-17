# FactoryGuard AI application image (API / worker / dashboard select via command).
# Multi-arch: works on linux/arm64 (GB10) and linux/amd64 (CI, Azure).
# Torch is intentionally NOT in this image; the serving path loads
# CPU-compatible artifacts, and GPU training runs in the venv or an NGC image.

FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements/lock.txt requirements/lock.txt
RUN pip install --no-cache-dir --prefix=/install -r requirements/lock.txt
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install --no-deps .

FROM python:3.12-slim
# Security: dedicated non-root user, no shell tools beyond the base image.
RUN groupadd --gid 10001 factoryguard \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin factoryguard
COPY --from=builder /install /usr/local
WORKDIR /app
COPY --chown=factoryguard:factoryguard apps ./apps
COPY --chown=factoryguard:factoryguard configs ./configs
USER 10001:10001
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FG_ENVIRONMENT=local
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).status==200 else 1)"]
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
