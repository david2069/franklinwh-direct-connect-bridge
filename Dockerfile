# Standalone Docker: defaults to python:3.12-slim (glibc — reliable wheels).
# HA Add-on: the supervisor overrides BUILD_FROM with an arch-specific ALPINE base
# (see build.yaml). Works on both Debian (apt-get) and Alpine (apk).
ARG BUILD_FROM=python:3.12-slim
# Stamped by tools/build_image.sh so a running container can say WHICH source it is.
# Without it, "I rebuilt and tested" is unverifiable — and was wrong at least once.
ARG SOURCE_SHA=unknown
FROM $BUILD_FROM

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/
# Bundled library docs (mkdocs site) served at /guide. tools/build_image.sh builds it;
# a committed .gitkeep keeps the dir present for a bare `docker build` (then /guide 404s).
COPY docs_site/ /app/docs_site/
# Dependencies come from pyproject.toml — ONE list, not two. This used to hand-repeat the
# dependency list here and install with --no-deps, so the two could drift silently.
#
# wheels/ holds locally-built wheels when a developer runs tools/build_image.sh, which is
# how an unreleased library gets tested before it ships. A clean clone has only a
# .gitkeep, nothing is pre-installed, and pip resolves everything from PyPI — which is
# what an end user and the Home Assistant add-on builder get, with no sibling checkouts
# and no dev-cycle coupling. The directory must exist either way or this COPY fails.
COPY wheels/ /tmp/wheels/
RUN if ls /tmp/wheels/*.whl >/dev/null 2>&1; then \
        pip install --no-cache-dir /tmp/wheels/*.whl; \
    fi \
 && pip install --no-cache-dir -e ".[cloud]"

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 8101

# Liveness of the web app only (/api/live does NO device I/O), so an unreachable aGate
# never marks the container unhealthy — the bridge stays up by design when the gateway
# is down. stdlib python (no curl in slim/alpine); honours HTTP_PORT.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import os,sys,urllib.request; p=os.environ.get('HTTP_PORT','8101'); sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+p+'/api/live', timeout=4).status==200 else 1)"]

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["franklinwh-direct-connect-bridge", "run"]

ARG SOURCE_SHA
ENV BRIDGE_SOURCE_SHA=${SOURCE_SHA}
