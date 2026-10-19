#!/bin/sh
# Ubuntu noble userspace only: the host owns GPU kernel modules and firmware.
# The caller can omit AMD's proprietary AMF/ROCm stack with ENABLE_AMD_AMF=0.
set -eu
# shellcheck disable=SC1091
. /etc/os-release
test "$ID:$VERSION_CODENAME" = ubuntu:noble
case "${ENABLE_AMD_AMF:-1}" in 0|1) ;; *) echo 'ENABLE_AMD_AMF must be 0 or 1' >&2; exit 1 ;; esac
# i965 shaders and non-free iHD are in multiverse; libmfx1 is in universe.
sed -i 's/^Components:.*/Components: main restricted universe multiverse/' /etc/apt/sources.list.d/ubuntu.sources
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gpg \
    libva2 libva-drm2 libva-x11-2 vainfo clinfo ocl-icd-libopencl1 \
    mesa-va-drivers mesa-vulkan-drivers mesa-opencl-icd libvulkan1
# A stable arch-neutral path also works for older static FFmpeg/libva builds.
# Do not force LIBVA_DRIVER_NAME: iHD, i965 and radeonsi must remain selectable.
case "$(dpkg --print-architecture)" in
    amd64) driver_dir=/usr/lib/x86_64-linux-gnu/dri ;;
    arm64) driver_dir=/usr/lib/aarch64-linux-gnu/dri ;;
    *) echo 'Unsupported GPU userspace architecture' >&2; exit 1 ;;
esac
mkdir -p /usr/local/lib
ln -sfn "$driver_dir" /usr/local/lib/dri
# Intel's graphics PPA publishes modern iHD/OpenCL/oneVPL packages for noble.
# Only amd64 has these Intel/AMD proprietary packages. Mesa also works on arm64.
if [ "$(dpkg --print-architecture)" = amd64 ]; then
    key=0C0E6AF955CE463C03FC51574D098D70AFBE5E1F
    curl -fsSL --retry 3 "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x${key}" -o /tmp/intel-graphics.key
    gpg --show-keys --with-colons /tmp/intel-graphics.key | grep -F "fpr:::::::::${key}:"
    gpg --batch --yes --dearmor -o /usr/share/keyrings/intel-graphics-ppa.gpg /tmp/intel-graphics.key
    echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/intel-graphics-ppa.gpg] https://ppa.launchpadcontent.net/kobuk-team/intel-graphics/ubuntu noble main' > /etc/apt/sources.list.d/intel-graphics-ppa.list
    apt-get update
    apt-get install -y --no-install-recommends \
        intel-media-va-driver-non-free i965-va-driver-shaders intel-opencl-icd libigfxcmrt7 \
        libmfx1 libmfx-gen1.2 libvpl2
    # Media SDK's libmfxhw64 is the Gen9 runtime; oneVPL's libmfx-gen is Gen12+.
    # Modern OpenCL (IGC 2) and legacy1 OpenCL (IGC 1) have separate libraries/ICDs.
    curl -fL --retry 3 https://github.com/intel/intel-graphics-compiler/releases/download/igc-1.0.17537.24/intel-igc-core_1.0.17537.24_amd64.deb -o /tmp/intel-igc-core.deb
    curl -fL --retry 3 https://github.com/intel/intel-graphics-compiler/releases/download/igc-1.0.17537.24/intel-igc-opencl_1.0.17537.24_amd64.deb -o /tmp/intel-igc-opencl.deb
    curl -fL --retry 3 https://github.com/intel/compute-runtime/releases/download/24.35.30872.36/intel-opencl-icd-legacy1_24.35.30872.36_amd64.deb -o /tmp/intel-opencl-icd-legacy1.deb
    printf '%s  %s\n' \
        c1e1ecdfe2064c047c552651cfdcdafc504f2033afafba65654338b880048b67 /tmp/intel-igc-core.deb \
        dd016400f87fa2b6a9fa9fbcca7eb4a2629174a29de679709f9bec5cede88b0e /tmp/intel-igc-opencl.deb \
        bbe71e4f414259e06a10cde72c29a2bd78d41b2bb2f6f8463b1806797fe66e85 /tmp/intel-opencl-icd-legacy1.deb | sha256sum -c -
    apt-get install -y --no-install-recommends /tmp/intel-igc-core.deb /tmp/intel-igc-opencl.deb /tmp/intel-opencl-icd-legacy1.deb
    test -s /etc/OpenCL/vendors/intel.icd
    test -s /etc/OpenCL/vendors/intel_legacy1.icd
    if [ "${ENABLE_AMD_AMF:-1}" = 1 ]; then
        curl -fsSL --retry 3 https://repo.radeon.com/rocm/rocm.gpg.key | gpg --batch --yes --dearmor -o /usr/share/keyrings/rocm-keyring.gpg
        # All AMD repositories use the same 6.4.4 release; no amdgpu-install/DKMS.
        echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/rocm-keyring.gpg] https://repo.radeon.com/amdgpu/6.4.4/ubuntu noble main proprietary' > /etc/apt/sources.list.d/amdgpu.list
        echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/rocm-keyring.gpg] https://repo.radeon.com/rocm/apt/6.4.4 noble main' > /etc/apt/sources.list.d/rocm.list
        apt-get update
        apt-get install -y --no-install-recommends \
            amf-amdgpu-pro=1.4.37-2203192.24.04 \
            libamdenc-amdgpu-pro=25.10-2203192.24.04 \
            rocm-opencl-runtime=6.4.4.60404-129~24.04
    fi
    rm -f /tmp/intel-graphics.key /tmp/intel-igc-core.deb /tmp/intel-igc-opencl.deb /tmp/intel-opencl-icd-legacy1.deb
fi
ldconfig
rm -rf /var/lib/apt/lists/*
