# Standalone Docker: defaults to python:3.12-slim (glibc — reliable wheels).
# HA Add-on: the supervisor overrides BUILD_FROM with an arch-specific ALPINE base
# (see build.yaml). Works on both Debian (apt-get) and Alpine (apk).
ARG BUILD_FROM=python:3.12-slim
FROM $BUILD_FROM

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/
# Bundled library docs (mkdocs site) served at /guide. tools/build_image.sh builds it;
# a committed .gitkeep keeps the dir present for a bare `docker build` (then /guide 404s).
COPY docs_site/ /app/docs_site/
# franklinwh-direct-connect-api: prefer a locally-built wheel (tools/build_image.sh drops it in
# ./wheels/ — auth-free while the repo is private); fall back to PyPI once published.
COPY wheels/ /tmp/wheels/
RUN if ls /tmp/wheels/*.whl >/dev/null 2>&1; then \
        pip install --no-cache-dir /tmp/wheels/*.whl; \
    else \
        pip install --no-cache-dir franklinwh-direct-connect-api; \
    fi \
 && pip install --no-cache-dir \
        fastapi "uvicorn>=0.29" jinja2 "pydantic>=2" "pydantic-settings>=2" "paho-mqtt>=2" \
        "franklinwh-modbus>=0.9" "croniter>=2.0" \
 && pip install --no-cache-dir --no-deps -e .

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8101

# Liveness of the web app only (/api/live does NO device I/O), so an unreachable aGate
# never marks the container unhealthy — the bridge stays up by design when the gateway
# is down. stdlib python (no curl in slim/alpine); honours HTTP_PORT.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import os,sys,urllib.request; p=os.environ.get('HTTP_PORT','8101'); sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+p+'/api/live', timeout=4).status==200 else 1)"]

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["franklinwh-local-bridge", "run"]
