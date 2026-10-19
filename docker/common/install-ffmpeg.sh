#!/bin/sh
# BtbN's GPL build includes ARIB captions and all GPU encoders. Jellyfin 7's
# noble package omits libaribb24/libaribcaption, so it cannot replace this build.
# Pin a month-end build: upstream retains these for two years (daily: 14 days).
# SHA256 values match the release assets and checksums.sha256.
set -eu
release=autobuild-2026-09-30-13-08
version=n8.1.3-9-g29e619e767
case "$(dpkg --print-architecture)" in
  amd64) arch=linux64; sha=97ce978979194b5cf7e06a5e68020dbdaa7a4f3294c5452b6a1bc347100dbb79 ;;
  arm64) arch=linuxarm64; sha=10523d1e0be6b3ce62a9708cc50815c4b5eb5f36ae147fbe2afeecda6f2d6845 ;;
  *) echo 'Unsupported FFmpeg architecture' >&2; exit 1 ;;
esac
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT HUP INT TERM
archive="ffmpeg-${version}-${arch}-gpl-8.1.tar.xz"
curl -fL --retry 3 "https://github.com/BtbN/FFmpeg-Builds/releases/download/${release}/${archive}" -o "$work/ffmpeg.tar.xz"
printf '%s  %s\n' "$sha" "$work/ffmpeg.tar.xz" | sha256sum -c -
tar -xJf "$work/ffmpeg.tar.xz" -C "$work" --strip-components=1
install -m 755 "$work/bin/ffmpeg" "$work/bin/ffprobe" /usr/local/bin/
# Preserve upstream licensing and build details along with the executables.
mkdir -p /usr/local/share/doc/ffmpeg
find "$work" -maxdepth 1 -type f ! -name ffmpeg.tar.xz -exec cp '{}' /usr/local/share/doc/ffmpeg/ ';'
ffmpeg -hide_banner -encoders > "$work/encoders" 2>&1
for encoder in libx264 libx265 h264_vaapi hevc_vaapi h264_amf hevc_amf h264_nvenc hevc_nvenc; do
    grep -w "$encoder" "$work/encoders"
done
if [ "$arch" = linux64 ]; then
    grep -w h264_qsv "$work/encoders"
    grep -w hevc_qsv "$work/encoders"
fi
ffmpeg -hide_banner -decoders > "$work/decoders" 2>&1
grep -w libaribb24 "$work/decoders"
ffmpeg -hide_banner -filters > "$work/filters" 2>&1
grep -w subtitles "$work/filters"
ffmpeg -hide_banner -loglevel error -f lavfi -i color=size=64x64:rate=1 -t 1 -c:v libx264 -f null -
