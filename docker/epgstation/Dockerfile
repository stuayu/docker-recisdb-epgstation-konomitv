FROM ubuntu:24.04 AS node-runtime
COPY docker/common/install-node.sh /tmp/install-node.sh
RUN sh /tmp/install-node.sh && rm /tmp/install-node.sh

FROM node-runtime AS builder
ARG EPGSTATION_REPO=https://github.com/stuayu/EPGStation.git
ARG EPGSTATION_REF=main
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git clone "${EPGSTATION_REPO}" . && git fetch --tags origin "${EPGSTATION_REF}" && git checkout "${EPGSTATION_REF}"
WORKDIR /src/client
RUN npm install --no-save
WORKDIR /src
RUN npm install --no-save
RUN npm run build

FROM node-runtime
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates gettext-base util-linux curl xz-utils libicu74 libssl3t64 zlib1g libstdc++6 fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
ARG INSTALL_AMATSUKAZE=0
ARG AMATSUKAZE_VERSION=1.1.1.2
ARG TARGETARCH
ARG ENABLE_AMD_AMF=1
COPY docker/common/install-gpu-runtime.sh /tmp/install-gpu-runtime.sh
RUN sh /tmp/install-gpu-runtime.sh && rm /tmp/install-gpu-runtime.sh
ENV NVIDIA_VISIBLE_DEVICES=all NVIDIA_DRIVER_CAPABILITIES=compute,utility,video
ENV LIBVA_DRIVERS_PATH=/usr/local/lib/dri
COPY docker/common/install-ffmpeg.sh /tmp/install-ffmpeg.sh
RUN sh /tmp/install-ffmpeg.sh && rm /tmp/install-ffmpeg.sh
# Release workflow publishes a self-contained .NET single-file executable.
RUN mkdir -p /opt/amatsukaze \
    && if [ "$INSTALL_AMATSUKAZE" = 1 ]; then \
         case "$TARGETARCH" in amd64) archive_arch=x64;; arm64) archive_arch=arm64;; *) echo "Unsupported AddTask architecture: $TARGETARCH" >&2; exit 1;; esac; \
         curl -fL --retry 3 "https://github.com/rigaya/Amatsukaze/releases/download/${AMATSUKAZE_VERSION}/AmatsukazeAddTask_linux_${AMATSUKAZE_VERSION}_${archive_arch}.tar.xz" -o /tmp/addtask.tar.xz \
         && tar -xJf /tmp/addtask.tar.xz -C /opt/amatsukaze \
         && chmod 755 /opt/amatsukaze/AmatsukazeAddTask \
         && rm /tmp/addtask.tar.xz; \
       fi
WORKDIR /app
COPY --from=builder /src/ /app/
RUN cp /app/config/enc.js.template /app/config/enc.js
COPY docker/epgstation/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN mkdir -p /app/config /app/data /app/recorded /app/thumbnail /app/drop
RUN chmod 755 /usr/local/bin/entrypoint.sh
EXPOSE 8888
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
