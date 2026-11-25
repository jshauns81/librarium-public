FROM node:24.22.1-bookworm-slim@sha256:55fb5f5a527ea2c5c4a95f963e48ef90aa38c7b346054fdc8ee9957a2b55d205 AS frontend
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build && cp node_modules/@fontsource-variable/literata/LICENSE dist/literata-license.txt \
    && cp node_modules/@fontsource-variable/eb-garamond/LICENSE dist/eb-garamond-license.txt \
    && cp node_modules/@fontsource/cinzel/LICENSE dist/cinzel-license.txt \
    && cp node_modules/@fontsource/cinzel-decorative/LICENSE dist/cinzel-decorative-license.txt \
    && cp vendor/foliate-js/LICENSE dist/foliate-js-license.txt

FROM python:3.14.9-slim-bookworm@sha256:945c2676dc2b18e0c1f16879244122c57c0ffede60006bf3df159c507a31bcae AS python-base

FROM python-base AS native-build
RUN rm -f /etc/apt/sources.list.d/debian.sources && \
    printf 'Acquire::Retries "5";\n' > /etc/apt/apt.conf.d/80-retries && \
    printf '%s\n' \
      'deb [check-valid-until=no signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://snapshot.debian.org/archive/debian/20261027T000000Z/ bookworm main' \
      'deb [check-valid-until=no signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://snapshot.debian.org/archive/debian/20261027T000000Z/ bookworm-updates main' \
      'deb [check-valid-until=no signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://snapshot.debian.org/archive/debian-security/20261027T000000Z/ bookworm-security main' \
      > /etc/apt/sources.list && \
    apt-get update && \
    apt-get install --yes --no-install-recommends gcc libc6-dev make zlib1g-dev ca-certificates && \
    rm -rf /var/lib/apt/lists/*
COPY scripts/build_libarchive.py /build/build_libarchive.py
RUN python /build/build_libarchive.py --prefix /opt/libarchive --build-dir /build

FROM python-base AS epubcheck-build
ARG TARGETARCH
RUN test "$TARGETARCH" = amd64
ADD --checksum=sha256:a535a1df9c6284d9618872984e026ae0352d1f7e9e0605425c0e6114f47351dd https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.13%2B9/OpenJDK21U-jre_x64_linux_hotspot_21.0.13_9.tar.gz /build/java.tar.gz
RUN mkdir -p /opt/java/openjdk && \
    tar --extract --gzip --file=/build/java.tar.gz --directory=/opt/java/openjdk --strip-components=1 --no-same-owner && \
    rm /build/java.tar.gz
COPY scripts/install_epubcheck.py /build/install_epubcheck.py
COPY backend/librarium/epubcheck_distribution.json /build/epubcheck_distribution.json
RUN python /build/install_epubcheck.py --manifest /build/epubcheck_distribution.json --prefix /opt/epubcheck && \
    /opt/java/openjdk/bin/java -jar /opt/epubcheck/epubcheck.jar --version

FROM python-base AS identity-build
WORKDIR /identity
COPY backend/ /identity/backend/
COPY --from=frontend /ui/dist/ /identity/frontend/dist/
COPY Dockerfile requirements.txt /identity/
COPY scripts/release.py scripts/build_libarchive.py scripts/install_epubcheck.py /identity/scripts/
RUN python scripts/release.py build-identity --output /identity/build-identity.json

FROM python-base
LABEL org.opencontainers.image.source="https://github.com/jshauns81/librarium-public"
COPY LICENSE /usr/share/doc/librarium/LICENSE
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LIBARCHIVE=/opt/libarchive/lib/libarchive.so.13.8.10 \
    LIBRARIUM_EPUBCHECK_DIR=/opt/epubcheck LIBRARIUM_JAVA=/opt/java/openjdk/bin/java
RUN rm -f /etc/apt/sources.list.d/debian.sources && \
    printf 'Acquire::Retries "5";\n' > /etc/apt/apt.conf.d/80-retries && \
    printf '%s\n' \
      'deb [check-valid-until=no signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://snapshot.debian.org/archive/debian/20261027T000000Z/ bookworm main' \
      'deb [check-valid-until=no signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://snapshot.debian.org/archive/debian/20261027T000000Z/ bookworm-updates main' \
      'deb [check-valid-until=no signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://snapshot.debian.org/archive/debian-security/20261027T000000Z/ bookworm-security main' \
      > /etc/apt/sources.list && \
    apt-get update && \
    apt-get install --yes --no-install-recommends libseccomp2 fontconfig ca-certificates && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt && useradd --uid 10001 --create-home librarium
COPY --from=native-build /opt/libarchive/lib/libarchive.so.13.8.10 /opt/libarchive/lib/libarchive.so.13.8.10
COPY --from=native-build /opt/libarchive/COPYING /opt/libarchive/COPYING
COPY --from=epubcheck-build /opt/java/openjdk/ /opt/java/openjdk/
COPY --from=epubcheck-build /opt/epubcheck/ /opt/epubcheck/
COPY backend/ /app/backend/
COPY --from=frontend /ui/dist/ /app/frontend/dist/
COPY --from=identity-build /identity/build-identity.json /app/backend/librarium/build-identity.json
USER 10001
WORKDIR /app/backend
EXPOSE 8123
CMD ["gunicorn", "librarium.wsgi:application", "--bind", "0.0.0.0:8123", "--workers", "2", "--access-logfile", "-", "--access-logformat", "%(t)s %(h)s %(r)s %(s)s %(b)s duration_us=%(D)s", "--no-control-socket"]
