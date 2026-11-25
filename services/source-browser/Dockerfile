FROM ghcr.io/browserless/chrome@sha256:e4ff3bb8537fe4c2f2c102b7984f3b71250bb323f8ce7ff5b1127c76bec1bf40 AS browser-files
COPY LICENSE /usr/share/doc/librarium/LICENSE
COPY services/source-browser/browser.cjs /role/browser.cjs
COPY backend/librarium/__init__.py backend/librarium/cover_source_protocol.py backend/librarium/cover_source_fetch.py backend/librarium/source_browser.py /role/librarium/
RUN python3 -c "from pathlib import Path; [compile(p.read_bytes(), str(p), 'exec') for p in Path('/role/librarium').glob('*.py')]"
USER root
RUN rm -f /etc/ssh/ssh_host_* && \
    rm -rf /root/.npm /usr/src/app/static && \
    ln -sf "$(command -v node)" /usr/local/bin/node && \
    install -d -o 999 -g 999 /data/profile

# Copy the sanitized filesystem so deleted files cannot survive in parent layers.
FROM scratch
COPY --from=browser-files / /
LABEL org.opencontainers.image.source="https://github.com/jshauns81/librarium-public"
ENV LANG=C.UTF-8 PYTHONPATH=/role HOME=/tmp
USER 999:999
ENTRYPOINT ["python3", "-m", "librarium.source_browser"]
