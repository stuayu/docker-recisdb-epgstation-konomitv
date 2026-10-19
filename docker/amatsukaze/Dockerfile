# Adapted from rigaya/Amatsukaze tag 1.1.1.2 docker/Dockerfile.
# https://github.com/rigaya/Amatsukaze/blob/1.1.1.2/docker/Dockerfile
# Release URL pinned; defaults retained outside persistent bind mounts.
# 配布アーカイブを使用するLinuxコンテナ
FROM ubuntu:24.04 AS fdkaac-builder

ARG FDK_AAC_REV=d8e6b1a3aa606c450241632b64b703f21ea31ce3
ARG FDKAAC_VER=v1.0.6

# fdkaacは配布アーカイブに含めず、ソースからビルドする
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential ca-certificates git autoconf automake libtool pkg-config \
    && git clone https://github.com/mstorsjo/fdk-aac.git /tmp/fdk-aac \
    && cd /tmp/fdk-aac \
    && git checkout "$FDK_AAC_REV" \
    && ./autogen.sh \
    && ./configure --disable-shared --prefix=/tmp/fdk-aac-libs \
    && make -j"$(nproc)" \
    && make install \
    && git clone --depth=1 --branch "$FDKAAC_VER" https://github.com/nu774/fdkaac.git /tmp/fdkaac \
    && cd /tmp/fdkaac \
    && autoreconf -i \
    && PKG_CONFIG_PATH=/tmp/fdk-aac-libs/lib/pkgconfig ./configure --prefix=/tmp/fdkaac-install \
    && make -j"$(nproc)" \
    && make install \
    && mkdir -p /fdkaac-output \
    && install -D /tmp/fdkaac-install/bin/fdkaac /fdkaac-output/fdkaac \
    && rm -rf /var/lib/apt/lists/*

# Battlemage等の新しいGPUとMesaのOpenCL (rusticl) を使うため、Ubuntu 24.04をベースにする
# Amatsukaze本体のCUDAはcudartを静的リンクしており、ホストのlibcuda.so.1だけを使うため、
# nvidia/cudaのベースイメージは不要 (NVIDIA_REQUIRE_CUDAで古いドライバが弾かれるのも避けられる)
FROM ubuntu:24.04

ARG ARCH=amd64
# VCEEncCは常にVA-API (Mesa) で導入し、AMFは任意とする
ARG ENABLE_VCEENC_AMF=1
ARG QSVENCC_VER=8.33
ARG NVENCC_VER=9.38
ARG VCEENCC_VER=9.21
# NVEncCのnvrtc用。24.04向けリポジトリに11.8は無いため、22.04向けのdebを直接導入する
# NVEncCは無印のlibnvrtc.soをdlopenするが、このdebには含まれないためリンクを追加する
ARG CUDA_NVRTC_DEB=cuda-nvrtc-11-8_11.8.89-1_amd64.deb
ARG CUDA_NVRTC_SHA256=6f083fcd63b7f8ef7478bfb7b8aba938d8ca0b5684d610df1243302b12a54f06
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Tokyo
ENV LANG=ja_JP.UTF-8
ENV LC_ALL=ja_JP.UTF-8
ENV LC_CTYPE=ja_JP.UTF-8
ENV PATH="/app/exe_files:$PATH"
# NVIDIA Container ToolkitにGPUとドライバ機能 (CUDA/NVENC/NVDEC) の注入を要求する
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility,video
ENV LIBVA_DRIVERS_PATH=/usr/local/lib/dri

# Same noble GPU runtimes as the other encoding containers; no host driver install.
COPY docker/common/install-gpu-runtime.sh /tmp/install-gpu-runtime.sh
RUN ENABLE_AMD_AMF="$ENABLE_VCEENC_AMF" sh /tmp/install-gpu-runtime.sh && rm /tmp/install-gpu-runtime.sh

# Fonts/Python plus rigaya encoders; the release bundle supports amd64 only.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl wget tzdata locales gosu python3 xz-utils \
        fontconfig fontconfig-config fonts-noto-cjk \
    && wget -q "https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/${CUDA_NVRTC_DEB}" -O /tmp/cuda-nvrtc.deb \
    && echo "${CUDA_NVRTC_SHA256}  /tmp/cuda-nvrtc.deb" | sha256sum -c - \
    && apt-get install -y --no-install-recommends /tmp/cuda-nvrtc.deb \
    && ln -sf libnvrtc.so.11.2 /usr/local/cuda-11.8/targets/x86_64-linux/lib/libnvrtc.so \
    && echo /usr/local/cuda-11.8/targets/x86_64-linux/lib > /etc/ld.so.conf.d/cuda-nvrtc.conf \
    && ldconfig \
    && wget -q "https://github.com/rigaya/QSVEnc/releases/download/${QSVENCC_VER}/qsvencc_${QSVENCC_VER}_${ARCH}.deb" -O /tmp/qsvencc.deb \
    && apt-get install -y --no-install-recommends /tmp/qsvencc.deb \
    && wget -q "https://github.com/rigaya/NVEnc/releases/download/${NVENCC_VER}/nvencc_${NVENCC_VER}_${ARCH}.deb" -O /tmp/nvencc.deb \
    && apt-get install -y --no-install-recommends /tmp/nvencc.deb \
    && wget -q "https://github.com/rigaya/VCEEnc/releases/download/${VCEENCC_VER}/vceencc_${VCEENCC_VER}_${ARCH}.deb" -O /tmp/vceencc.deb \
    && apt-get install -y --no-install-recommends /tmp/vceencc.deb \
    && if [ ! -e /lib/x86_64-linux-gnu/libOpenCL.so ] && [ -e /lib/x86_64-linux-gnu/libOpenCL.so.1 ]; then \
        ln -s /lib/x86_64-linux-gnu/libOpenCL.so.1 /lib/x86_64-linux-gnu/libOpenCL.so; \
    fi \
    && fc-cache -f \
    && locale-gen ja_JP.UTF-8 en_US.UTF-8 \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo "$TZ" > /etc/timezone \
    && rm -f /tmp/cuda-nvrtc.deb /tmp/qsvencc.deb /tmp/nvencc.deb /tmp/vceencc.deb \
    && rm -rf /var/lib/apt/lists/*

# Amatsukaze本体を展開する
ARG AMATSUKAZE_VERSION=1.1.1.2
ARG TARGETARCH
COPY --from=fdkaac-builder /fdkaac-output/ /usr/local/bin/
RUN test "$TARGETARCH" = amd64 \
    && mkdir -p /app \
    && curl -fL --retry 3 "https://github.com/rigaya/Amatsukaze/releases/download/${AMATSUKAZE_VERSION}/Amatsukaze_linux_${AMATSUKAZE_VERSION}_x64.tar.xz" -o /tmp/amatsukaze.tar.xz \
    && tar -xJf /tmp/amatsukaze.tar.xz -C /app \
    && rm /tmp/amatsukaze.tar.xz \
    && grep -Fq '"complete":true' /app/basepkg-manifest.json \
    && mkdir -p /app/bat /app/config /app/recorded /app/logo /app/output /app/profile /app/temp

# ローカルアーカイブでデバッグするときだけ、ファイル名を合わせて次の2命令を有効にする
#COPY Amatsukaze_linux_trial_x64.tar.xz /tmp/amatsukaze-debug.tar.xz
#RUN tar -xJf /tmp/amatsukaze-debug.tar.xz -C /app \
#    && grep -Fq '"complete":true' /app/basepkg-manifest.json \
#    && rm /tmp/amatsukaze-debug.tar.xz

# Faster-Whisper-XXLを展開する
ARG ENABLE_FASTER_WHISPER=0
ARG FASTER_WHISPER_VER=r245.4
RUN if [ "$ENABLE_FASTER_WHISPER" = "1" ]; then \
        wget -q "https://github.com/Purfview/whisper-standalone-win/releases/download/Faster-Whisper-XXL/Faster-Whisper-XXL_${FASTER_WHISPER_VER}_linux.7z" -O /tmp/faster-whisper.7z \
        && mkdir -p /opt \
        && /app/exe_files/7z/7zzs x /tmp/faster-whisper.7z -o/opt/ \
        && chmod 755 /opt/Faster-Whisper-XXL/faster-whisper-xxl \
        && ln -s /opt/Faster-Whisper-XXL /app/exe_files/Faster-Whisper-XXL \
        && rm -f /tmp/faster-whisper.7z; \
    fi

WORKDIR /app

# 起動時にホストのUIDとGIDへ合わせる
RUN cat <<'ENTRYPOINT_SCRIPT' > /app/entrypoint.sh && chmod +x /app/entrypoint.sh
#!/bin/bash
set -e
umask 022

DEFAULT_UID=${RUN_UID:-1000}
DEFAULT_GID=${RUN_GID:-1000}
if ! getent group "$DEFAULT_GID" >/dev/null 2>&1; then groupadd -g "$DEFAULT_GID" appgroup; fi
if ! getent passwd "$DEFAULT_UID" >/dev/null 2>&1; then useradd -u "$DEFAULT_UID" -g "$DEFAULT_GID" -m -s /bin/bash appuser; fi

USER_NAME=$(id -nu "$DEFAULT_UID")
# Existing image users must use the selected primary group as well.
usermod -g "$DEFAULT_GID" "$USER_NAME"
# 複数GPUを並列で使えるよう、渡されたすべてのGPUデバイスの所有グループに参加させる
for GPU_NODE in /dev/dri/renderD* /dev/dri/card* /dev/kfd; do
    [ -c "$GPU_NODE" ] || continue
    GPU_GID=$(stat -c "%g" "$GPU_NODE")
    GPU_GROUP=$(getent group "$GPU_GID" | cut -d: -f1 || true)
    if [ -z "$GPU_GROUP" ]; then
        GPU_GROUP="gpu$GPU_GID"
        groupadd -g "$GPU_GID" "$GPU_GROUP"
    fi
    usermod -aG "$GPU_GROUP" "$USER_NAME"
done
chown -R --no-dereference "$DEFAULT_UID:$DEFAULT_GID" /app
if [ -d /opt/Faster-Whisper-XXL ]; then
    find /opt/Faster-Whisper-XXL -type d -exec chown "$DEFAULT_UID:$DEFAULT_GID" {} +
fi
if [ -x /app/exe_files/AmatsukazeDockerConfigFix ]; then
    gosu "$DEFAULT_UID" /app/exe_files/AmatsukazeDockerConfigFix \
        /app/config/AmatsukazeServer.xml /app/exe_files || \
        echo "警告: Docker用実行ファイル設定の補正に失敗しました" >&2
fi
exec gosu "$DEFAULT_UID" "$@"
ENTRYPOINT_SCRIPT

RUN mkdir -p /opt/amatsukaze-defaults \
    && for dir in avs bat config data drcs JL logo profile input output; do \
         mkdir -p "/app/$dir" "/opt/amatsukaze-defaults/$dir"; \
         cp -a "/app/$dir/." "/opt/amatsukaze-defaults/$dir/"; \
       done
COPY docker/amatsukaze/EPGStation.profile /opt/amatsukaze-defaults/profile/EPGStation.profile
COPY docker/amatsukaze/entrypoint.sh /usr/local/bin/stack-entrypoint.sh
RUN chmod 755 /usr/local/bin/stack-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/stack-entrypoint.sh"]
CMD ["./AmatsukazeServer.sh"]

COPY scripts/editable.py /opt/stack-scripts/editable.py
