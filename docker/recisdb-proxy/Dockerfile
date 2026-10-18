FROM node:lts-bookworm-slim AS web-builder
ARG RECISDB_REPO=https://github.com/stuayu/recisdb-proxy-rs.git
ARG RECISDB_REF=main
WORKDIR /src
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && git clone --recursive "${RECISDB_REPO}" . \
    && git fetch --tags origin "${RECISDB_REF}" \
    && git checkout "${RECISDB_REF}" \
    && git submodule update --init --recursive
WORKDIR /src/web-ui
RUN npm ci && npm run build

FROM rust:bookworm AS builder
ARG RECISDB_REPO=https://github.com/stuayu/recisdb-proxy-rs.git
ARG RECISDB_REF=main
RUN apt-get update && apt-get install -y --no-install-recommends git cmake pkg-config libpcsclite-dev libssl-dev build-essential ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git clone --recursive "${RECISDB_REPO}" . \
    && git fetch --tags origin "${RECISDB_REF}" \
    && git checkout "${RECISDB_REF}" \
    && git submodule update --init --recursive
COPY --from=web-builder /src/recisdb-proxy/static/vue /src/recisdb-proxy/static/vue
ENV PKG_CONFIG_ALLOW_CROSS=1
# Cargo package uses bundled libaribb25. Do not install libaribb25-dev or a shared libaribb25.so.
RUN cargo build --release -p recisdb-proxy

FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive TZ=Asia/Tokyo
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl libssl3 libgcc-s1 libstdc++6 gettext-base tzdata xz-utils \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app && useradd --system --gid app --home-dir /data --no-create-home app
RUN install -d -o app -g app /opt/recisdb-proxy/thirdparty
COPY --from=builder --chown=app:app /src/target/release/recisdb-proxy /opt/recisdb-proxy/recisdb-proxy
COPY docker/recisdb-proxy/entrypoint.sh /usr/local/bin/entrypoint.sh
ENV PATH="/opt/recisdb-proxy:${PATH}"
RUN chmod 755 /usr/local/bin/entrypoint.sh && mkdir -p /config /data /data/logs && chown -R app:app /data
USER app
VOLUME ["/config", "/data"]
EXPOSE 40070 40080
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
