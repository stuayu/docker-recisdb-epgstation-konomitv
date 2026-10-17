ARG NODE_VERSION=24
FROM node:${NODE_VERSION}-trixie AS builder
ARG EPGSTATION_REPO=https://github.com/stuayu/EPGStation.git
ARG EPGSTATION_REF=master
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git clone "${EPGSTATION_REPO}" . && git fetch --tags origin "${EPGSTATION_REF}" && git checkout "${EPGSTATION_REF}"
WORKDIR /src/client
RUN npm install --no-save
WORKDIR /src
RUN npm install --no-save
RUN npm run build

FROM node:24-trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates gettext-base \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /src/ /app/
COPY docker/epgstation/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN mkdir -p /app/config /app/data /app/recorded
RUN chmod 755 /usr/local/bin/entrypoint.sh
EXPOSE 8888
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
