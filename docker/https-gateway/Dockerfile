ARG GO_VERSION=1.24
FROM golang:${GO_VERSION}-bookworm AS builder
ARG AKEBI_REPO=https://github.com/tsukumijima/Akebi.git
ARG AKEBI_REF=8ddba6a29b858567ab286b5d31daebf2ff683e94
WORKDIR /src
RUN git clone "${AKEBI_REPO}" . \
    && git checkout --detach "${AKEBI_REF}" \
    && cd https-server \
    && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/akebi-https-server .

FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini netcat-openbsd \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin akebi
COPY --from=builder /out/akebi-https-server /usr/local/bin/akebi-https-server
COPY docker/https-gateway/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/entrypoint.sh /usr/local/bin/akebi-https-server
USER akebi
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
