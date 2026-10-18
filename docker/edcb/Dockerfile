ARG EDCB_EPGSTATION_ENABLED=0
FROM rust:bookworm AS uploader-1
ARG EDCB_TO_EPGSTATION_REPO=https://github.com/stuayu/EDCB-to-EPGStation.git
ARG EDCB_TO_EPGSTATION_REF=main
ARG EDCB_EPGSTATION_ENABLED=0
RUN mkdir -p /out && if [ "$EDCB_EPGSTATION_ENABLED" = 1 ]; then \
    apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && git clone "$EDCB_TO_EPGSTATION_REPO" /src && cd /src \
    && git fetch origin "$EDCB_TO_EPGSTATION_REF" && git checkout --detach FETCH_HEAD \
    && cargo build --locked --release \
    && cp target/release/edcb_to_epgstation_ts /out/; fi

FROM debian:bookworm-slim AS uploader-0
RUN mkdir /out

FROM uploader-${EDCB_EPGSTATION_ENABLED} AS uploader

FROM debian:bookworm AS builder
ARG EDCB_REPO=https://github.com/stuayu/EDCB.git
ARG EDCB_REF=my-build
ARG EDCB_WEBUI_REPO=https://github.com/EMWUI/EDCB_Material_WebUI.git
ARG EDCB_WEBUI_REF=E3
ARG EDCB_BONDRIVER_REPO=https://github.com/matching/BonDriver_LinuxMirakc.git
ARG EDCB_BONDRIVER_REF=main
RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates build-essential liblua5.2-dev lua-zlib python3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git clone "$EDCB_REPO" edcb && cd edcb \
    && git fetch origin "$EDCB_REF" && git checkout --detach FETCH_HEAD \
    && make -C Document/Unix -j"$(nproc)" \
    && make -C Document/Unix install_u \
    && mkdir -p /var/local/edcb && make -C Document/Unix setup_ini \
    && rm /var/local/edcb/EpgTimerSrv.ini
RUN git clone "$EDCB_WEBUI_REPO" webui && cd webui \
    && git fetch origin "$EDCB_WEBUI_REF" && git checkout --detach FETCH_HEAD \
    && cp -a HttpPublic/. /var/local/edcb/HttpPublic/ \
    && mkdir -p /var/local/edcb/Setting && cp -a Setting/. /var/local/edcb/Setting/
COPY docker/edcb/patch-driver.py /tmp/patch-driver.py
RUN git clone "$EDCB_BONDRIVER_REPO" bondriver && cd bondriver \
    && git fetch origin "$EDCB_BONDRIVER_REF" && git checkout --detach FETCH_HEAD \
    && git submodule update --init --recursive \
    && python3 /tmp/patch-driver.py . && make -j"$(nproc)" \
    && install -m 755 BonDriver_LinuxMirakc.so /usr/local/lib/edcb/

FROM debian:bookworm-slim
ENV TZ=Asia/Tokyo LANG=C.UTF-8 EDCB_STACK_ROOT=/opt
# Debian provides the Lua 5.2 and zlib modules described in HowToBuild.txt.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates liblua5.2-0 lua-zlib libstdc++6 python3 python3-yaml tini gosu curl tzdata \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY --from=builder /usr/local/lib/edcb/ /usr/local/lib/edcb/
COPY --from=builder /var/local/edcb/ /opt/edcb-defaults/
COPY docker/edcb/entrypoint.sh /usr/local/bin/edcb-entrypoint.sh
COPY docker/edcb/configure.py docker/edcb/chset.py docker/edcb/post-record.py docker/edcb/post-record.sh /opt/edcb-stack/
COPY scripts/editable.py scripts/storage.py scripts/render-config.py /opt/scripts/
COPY templates/edcb/ /opt/templates/edcb/
COPY docker/edcb/upload_runtime.py /opt/edcb-stack/
COPY --from=uploader /out/ /opt/edcb-upload/
RUN chmod 755 /opt/edcb-stack/post-record.sh
RUN chmod 755 /usr/local/bin/edcb-entrypoint.sh
WORKDIR /var/local/edcb
EXPOSE 5510
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/edcb-entrypoint.sh"]
CMD ["EpgTimerSrv"]
