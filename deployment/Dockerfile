# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock pyproject.toml ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir --require-hashes -r requirements.lock
COPY src ./src
COPY config ./config
COPY docs ./docs
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home msnr && mkdir -p /app/var && chown -R msnr:msnr /app/var \
    && chmod -R a+rX /app/config /app/docs
USER msnr
ENV MPLCONFIGDIR=/app/var/cache/matplotlib XDG_CACHE_HOME=/app/var/cache
EXPOSE 8000
CMD ["msnr","serve","--host","0.0.0.0","--port","8000"]
