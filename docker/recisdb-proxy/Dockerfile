FROM ubuntu:24.04 AS web-builder
COPY docker/common/install-node.sh /tmp/install-node.sh
RUN sh /tmp/install-node.sh && rm /tmp/install-node.sh
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

FROM ubuntu:24.04 AS builder
COPY docker/common/install-rust.sh /tmp/install-rust.sh
RUN sh /tmp/install-rust.sh && rm /tmp/install-rust.sh
ENV PATH="/root/.cargo/bin:$PATH"
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

FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive TZ=Asia/Tokyo
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl libssl3t64 libgcc-s1 libstdc++6 gettext-base tzdata xz-utils \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app && useradd --system --gid app --home-dir /data --no-create-home app
# Keep Intel Gen9 Media SDK and modern oneVPL/OpenCL, Mesa and optional AMD AMF.
ARG ENABLE_AMD_AMF=1
COPY docker/common/install-gpu-runtime.sh /tmp/install-gpu-runtime.sh
RUN sh /tmp/install-gpu-runtime.sh && rm /tmp/install-gpu-runtime.sh
ENV NVIDIA_VISIBLE_DEVICES=all NVIDIA_DRIVER_CAPABILITIES=compute,utility,video
ENV LIBVA_DRIVERS_PATH=/usr/local/lib/dri
RUN install -d -o app -g app /opt/recisdb-proxy/thirdparty
COPY --from=builder --chown=app:app /src/target/release/recisdb-proxy /opt/recisdb-proxy/recisdb-proxy
COPY docker/recisdb-proxy/entrypoint.sh /usr/local/bin/entrypoint.sh
ENV PATH="/opt/recisdb-proxy:${PATH}"
RUN chmod 755 /usr/local/bin/entrypoint.sh && mkdir -p /config /data /data/logs && chown -R app:app /data
USER app
VOLUME ["/config", "/data"]
EXPOSE 40070 40080
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
