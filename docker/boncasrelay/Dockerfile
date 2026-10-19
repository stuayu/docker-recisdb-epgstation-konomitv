FROM ubuntu:24.04 AS builder
COPY docker/common/install-rust.sh /tmp/install-rust.sh
RUN sh /tmp/install-rust.sh && rm /tmp/install-rust.sh
ENV PATH="/root/.cargo/bin:$PATH"
ARG BONCASRELAY_REPO=https://github.com/stuayu/BonCasRelay.git
ARG BONCASRELAY_REF=main
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates build-essential python3 pkg-config libpcsclite-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git clone "$BONCASRELAY_REPO" . && git fetch origin "$BONCASRELAY_REF" && git checkout --detach FETCH_HEAD \
    && cargo build --locked --release --no-default-features -p boncasrelay
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends pcscd libpcsclite1 libccid tini ca-certificates python3 iproute2 && rm -rf /var/lib/apt/lists/*
COPY --from=builder /src/target/release/boncasrelay /usr/local/libexec/boncasrelay/boncasrelay
ENV LD_LIBRARY_PATH=/opt/boncasrelay
COPY docker/boncasrelay/runtime.py /usr/local/lib/boncasrelay/runtime.py
COPY docker/boncasrelay/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
