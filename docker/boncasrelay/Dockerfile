FROM rust:bookworm AS builder
ARG BONCASRELAY_REPO=https://github.com/stuayu/BonCasRelay.git
ARG BONCASRELAY_REF=main
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates build-essential python3 pkg-config libpcsclite-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git clone "$BONCASRELAY_REPO" . && git fetch origin "$BONCASRELAY_REF" && git checkout --detach FETCH_HEAD \
    && cargo build --locked --release --no-default-features -p boncasrelay
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends pcscd libpcsclite1 libccid tini ca-certificates python3 iproute2 && rm -rf /var/lib/apt/lists/*
COPY --from=builder /src/target/release/boncasrelay /usr/local/bin/boncasrelay
COPY docker/boncasrelay/runtime.py /opt/boncasrelay/runtime.py
COPY docker/boncasrelay/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
