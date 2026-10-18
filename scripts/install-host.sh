#!/usr/bin/env bash
# Privileged recipes. setup.sh displays this file and confirms before calling sudo.
set -Eeuo pipefail
component=${1:?component required}
# shellcheck disable=SC1091
source /etc/os-release
[[ $ID == debian || $ID == ubuntu ]] || { echo 'Debian / Ubuntu のみ対応'; exit 1; }
case $component in
  docker)
    apt-get update
    apt-get install -y ca-certificates curl
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/$ID
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    ;;
  px4)
    apt-get update
    apt-get install -y ca-certificates curl build-essential dkms "linux-headers-$(uname -r)"
    work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
    # px4_drv README v0.6.1: DKMS package installs firmware too.
    curl -fL --retry 3 https://github.com/tsukumijima/px4_drv/releases/download/v0.6.1/px4-drv-dkms_0.6.1_all.deb -o "$work/px4-drv-dkms_0.6.1_all.deb"
    chmod 755 "$work"; chmod 644 "$work/px4-drv-dkms_0.6.1_all.deb"
    apt-get install -y "$work/px4-drv-dkms_0.6.1_all.deb"
    modprobe px4_drv
    cat > /etc/udev/rules.d/99-px4video.rules <<'EOF'
KERNEL=="px*video*", GROUP="video", MODE="0660"
KERNEL=="isdb*video*", GROUP="video", MODE="0660"
KERNEL=="pt*video*", GROUP="video", MODE="0660"
EOF
    udevadm control --reload-rules
    udevadm trigger
    ;;
  nvidia)
    apt-get update
    apt-get install -y ca-certificates curl gnupg
    work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey -o "$work/key"
    gpg --batch --yes --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg "$work/key"
    curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list -o "$work/list"
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' "$work/list" > /etc/apt/sources.list.d/nvidia-container-toolkit.list
    apt-get update
    apt-get install -y nvidia-container-toolkit
    nvidia-ctk runtime configure --runtime=docker
    # Restarting Docker interrupts other containers; this is included in the confirmation.
    systemctl restart docker
    ;;
  *) echo "Unknown component: $component" >&2; exit 2;;
esac
