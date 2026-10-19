# Ubuntu 24.04 統一と GPU エンコードの実装・検証手順

この変更では、スタック側のビルド用・実行用イメージを Ubuntu 24.04 LTS に揃え、Intel / AMD / NVIDIA のユーザー空間ライブラリとデバイス設定を整備します。EPGStation、recisdb-proxy、KonomiTV、Amatsukaze は、各イメージ内で実際に短い動画をエンコードしてから利用方式を選びます。手動編集した設定は維持します。

本書のコマンドは x86_64 Linux の検証ホストで実行する手順です。今回の Mac 環境では Docker イメージの実ビルド、GPU へのアクセス、実放送の録画・再生を実施していません。パッケージ一覧や `ffmpeg -encoders` に名前が出ることだけでは、ハードウェアエンコード成功とは判定しません。

## ベースイメージの変更

「変更前」は、このリポジトリの作業前のコミットである `HEAD` の Dockerfile です。作業開始時点から存在した未コミット変更も含めた最終構成を「変更後」に記します。

| Dockerfile / ステージ | 変更前 | 変更後 |
| --- | --- | --- |
| `docker/recisdb-proxy/Dockerfile` / web-builder | `node:lts-bookworm-slim` | `ubuntu:24.04` + Node.js 公式バイナリ |
| 同 / builder | `rust:bookworm` | `ubuntu:24.04` + rustup |
| 同 / runtime | `debian:bookworm-slim` | `ubuntu:24.04` |
| `docker/epgstation/Dockerfile` / builder | `node:${NODE_VERSION}-trixie` (`NODE_VERSION=24`) | `ubuntu:24.04` 由来の `node-runtime` |
| 同 / runtime | `node:24-trixie-slim` | 同じ `node-runtime` |
| `docker/boncasrelay/Dockerfile` / builder | `rust:bookworm` | `ubuntu:24.04` + rustup |
| 同 / runtime | `debian:trixie-slim` | `ubuntu:24.04` |
| `docker/https-gateway/Dockerfile` / builder | `golang:${GO_VERSION}-bookworm` (`GO_VERSION=1.24`) | `ubuntu:24.04` + Go 公式バイナリ |
| 同 / runtime | `debian:bookworm-slim` | `ubuntu:24.04` |
| `docker/edcb/Dockerfile` / dashboard-builder | `node:24-bookworm-slim` | `ubuntu:24.04` + Node.js 公式バイナリ |
| 同 / uploader-1 | `rust:bookworm` | `ubuntu:24.04` + rustup (アップロード有効時のみ) |
| 同 / uploader-0 | `debian:bookworm-slim` | `ubuntu:24.04` |
| 同 / uploader | `uploader-${EDCB_EPGSTATION_ENABLED}` | 同じ選択式。選択先が Ubuntu 24.04 |
| 同 / builder | `debian:bookworm` | `ubuntu:24.04` |
| 同 / runtime | `debian:bookworm-slim` | `ubuntu:24.04` |
| `docker/amatsukaze/Dockerfile` / fdkaac-builder | `ubuntu:24.04` | `ubuntu:24.04` |
| 同 / runtime | `ubuntu:24.04` | `ubuntu:24.04`。GPU 依存を共通スクリプトへ移動 |
| KonomiTV ソースの `Dockerfile` / thirdparty-downloader | `ubuntu:24.04` | `ubuntu:24.04` |
| 同 / client-builder | `node:24-trixie` | `ubuntu:24.04` + Node.js 公式バイナリ |
| 同 / runtime | `nvidia/cuda:12.8.0-base-ubuntu24.04` | 同じ Ubuntu 24.04 ベースの CUDA イメージ |

KonomiTV の3行だけは、このタスク開始時点の既存変更後を比較元にしています。確認した外部チェックアウトの `HEAD` 自体は `ubuntu:22.04` / `node:20.16.0` / `nvidia/cuda:12.8.0-base-ubuntu22.04` であり、Ubuntu 24.04 化の既存変更を保持した上で Node.js ステージ等を揃えています。スタック側にも、作業開始時には一部を trixie に寄せる既存変更がありました。表はこれらを上書きして元に戻したという意味ではなく、最終的な noble 統一を示しています。

KonomiTV はこのリポジトリの外にある `KONOMITV_SOURCE` の Dockerfile を使います。そこに同じ修正を適用したソースを指定してください。スタック側だけを更新しても、別ディレクトリの Dockerfile は更新されません。MariaDB は既存の `mariadb:latest` を継続し、Dockerfile の対象に含めていません。

Ubuntu 内でソースからビルドすることで、Debian 側の新しい glibc や OpenSSL を前提とする実行ファイルを Ubuntu の最終イメージへコピーする構成を避けます。EPGStation のネイティブ依存は noble の `libicu74` / `libssl3t64`、recisdb-proxy は `libssl3t64` に合わせています。

## ツールチェーンと外部配布物

| 対象 | 固定値・取得方式 |
| --- | --- |
| Node.js | `24.22.0`。amd64 / arm64 の公式 tar.xz と SHA-256 を `docker/common/install-node.sh` に固定 |
| Rust | `1.99.1`。`docker/common/install-rust.sh` が rustup minimal で導入 |
| Go | `1.24.13`。amd64 / arm64 の公式 tar.gz と SHA-256 を `docker/common/install-go.sh` に固定 |
| EPGStation FFmpeg | BtbN `autobuild-2026-09-30-13-08`、`n8.1.3-9-g29e619e767`、`gpl-8.1`。amd64 / arm64 の SHA-256 を固定 |
| Intel legacy IGC | `1.0.17537.24` の core / OpenCL パッケージ。SHA-256 を固定 |
| Intel legacy1 OpenCL | `24.35.30872.36`。SHA-256 を固定 |
| AMD AMF | `amf-amdgpu-pro=1.4.37-2203192.24.04` |
| AMD encoder library | `libamdenc-amdgpu-pro=25.10-2203192.24.04` |
| ROCm OpenCL | `rocm-opencl-runtime=6.4.4.60404-129~24.04`。AMDGPU / ROCm リポジトリをともに `6.4.4` に統一 |
| Amatsukaze | `1.1.1.2`。サーバー配布物は x64、サービスは `linux/amd64` 固定 |
| Amatsukaze のエンコーダー | QSVEncC `8.33`、NVEncC `9.38`、VCEEncC `9.21` |
| Amatsukaze 用 CUDA NVRTC | `11.8.89-1`。deb の SHA-256 を固定 |
| fdkaac | `v1.0.6`。fdk-aac は `d8e6b1a3aa606c450241632b64b703f21ea31ce3` |
| KonomiTV thirdparty | 既存の `v0.14.1` 配布アーカイブ。Python / FFmpeg / Rigaya ツールはこの配布物を使用 |

固定バージョン以外の Ubuntu apt パッケージ、Intel PPA のパッケージ、アプリケーションの `main` 等の参照は更新され得ます。この表はビルド全体を完全再現可能にするものではありません。Node.js / Go のチェックサムはそれぞれ [Node.js 配布ディレクトリ](https://nodejs.org/dist/v24.22.0/SHASUMS256.txt)と [Go 配布一覧](https://go.dev/dl/?mode=json&include=all)が確認元です。

## GPU ランタイム

EPGStation、recisdb-proxy、Amatsukaze は `docker/common/install-gpu-runtime.sh` を使います。KonomiTV の Dockerfile にも同等の導入処理を置き、独立したビルドコンテキストからビルドできる構成にしています。EDCB、BonCasRelay、HTTPS gateway に映像エンコード用 GPU パッケージは追加しません。

| 系統 | コンテナへ入れる主なパッケージ | 用途 |
| --- | --- | --- |
| 共通 | `libva2`、`libva-drm2`、`libva-x11-2`、`vainfo`、`clinfo`、`ocl-icd-libopencl1`、`libvulkan1` | VA-API / OpenCL / Vulkan と診断 |
| Mesa | `mesa-va-drivers`、`mesa-vulkan-drivers`、`mesa-opencl-icd` | AMD 等の VA-API / Vulkan / OpenCL |
| Intel | `intel-media-va-driver-non-free`、`i965-va-driver-shaders`、`intel-opencl-icd`、`libigfxcmrt7` | iHD、旧世代 i965、現行 OpenCL |
| Intel QSV | `libmfx1`、`libmfx-gen1.2`、`libvpl2` | 旧 Media SDK と現行 oneVPL の両系統 |
| Intel 旧 OpenCL | legacy IGC と `intel-opencl-icd-legacy1` | 現行ランタイムだけでは対応しない旧世代向け |
| AMD AMF / ROCm | 上表の AMF、libamdenc、ROCm OpenCL | AMF と ROCm OpenCL。`ENABLE_AMD_AMF=0` で導入を省略可能 |
| NVIDIA | Container Toolkit によるホストライブラリ注入 | `NVIDIA_VISIBLE_DEVICES=all`、`NVIDIA_DRIVER_CAPABILITIES=compute,utility,video` |

Amatsukaze では既存の build ARG 名を保持し、`ENABLE_VCEENC_AMF=0` で AMF / ROCm を省略します。ほかの3イメージは `ENABLE_AMD_AMF=0` です。省略しても Mesa の VA-API は残ります。

Intel / AMD の追加パッケージは amd64 分岐で導入します。Intel の iHD / i965 や OpenCL ランタイムを同居させても、全世代・全機能の動作を保証するわけではありません。特に Gen9 では Media SDK 系と実機の組合せを確認します。[Intel Media SDK](https://github.com/Intel-Media-SDK/MediaSDK) と [oneVPL GPU runtime](https://github.com/intel/vpl-gpu-rt) は別の実装であり、oneVPL 側の導入だけを旧世代対応の証拠にはしません。

EPGStation・recisdb-proxy・Amatsukaze の3イメージには `LIBVA_DRIVERS_PATH=/usr/local/lib/dri` を設定し、共通導入処理から実際の multiarch DRI ディレクトリへリンクします。BtbN バイナリのように配布先 OS の既定 driver path を持たない場合も、noble の iHD / i965 / Mesa ドライバーへ到達させるためです。`LIBVA_DRIVER_NAME` は固定せず、すべての GPU を Intel ドライバーで開こうとする設定にはしません。KonomiTV には設定しません。同梱の rigaya 系エンコーダーは同梱 libva と `thirdparty/Library/dri` の iHD を使い、システムの新しい iHD を読ませると `iHD_drv_video.so has no function __vaDriverInit_1_0` で初期化に失敗するためです。

コンテナ内に GPU のカーネルモジュール、DKMS、ファームウェアは導入しません。ホスト側で動くドライバーとコンテナ内のユーザー空間ライブラリを組み合わせます。NVIDIA Container Toolkit の設定は [NVIDIA 公式手順](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)を確認してください。

## FFmpeg を一律 Jellyfin 版へ置き換えない理由

EPGStation は `docker/common/install-ffmpeg.sh` で BtbN の固定ビルドを `/usr/local/bin/ffmpeg` と `ffprobe` に配置します。日本の放送では GPU エンコーダーに加え、ARIB 字幕の取り扱いと字幕フィルターも必要です。今回選んだ配布物は、ビルド中に `libaribb24` decoder、`subtitles` filter、ソフトウェア / GPU encoder の有無を確認し、libx264 の短い実エンコードも実行します。

Jellyfin FFmpeg は GPU 対応の有力な配布物ですが、今回調べた noble 向け jellyfin-ffmpeg7 `7.1.4-3` は ARIB の `libaribb24` / `libaribcaption` を含まないため、既存の字幕機能を維持する置換先としては採用しません。確認した配布物の結果であり、Jellyfin FFmpeg の全バージョンについての断定ではありません。[同バージョンのビルド設定](https://github.com/jellyfin/jellyfin-ffmpeg/blob/v7.1.4-3/debian/rules)に両 ARIB ライブラリの有効化指定がないことも確認しました。更新時にも実バイナリの `-buildconf` / `-decoders` / `-filters` を比較してください。

recisdb-proxy の FFmpeg / tsreadex は Web API の自動セットアップで `data/recisdb/thirdparty` に保存し、コンテナへ bind mount します。GPU 判定は固定パスを推測せず、実行中サービスのプレビュー設定から認証付き API で取得した `command_path` を使います。KonomiTV は自身の thirdparty 配布物を継続し、Linux の FFmpeg パスは `/code/server/thirdparty/FFmpeg/ffmpeg.elf` です。

[recisdb-proxy の取得処理](https://github.com/stuayu/recisdb-proxy-rs/blob/feature/proxy/recisdb-proxy/src/preview_setup.rs)は BtbN の latest release から配布物を選びます。ローカルに取得済みの BtbN 9.0 バイナリと、今回固定した 8.1 バイナリでは、ロード対象名 `libva.so.2` / `libva-drm.so.2`、`libmfxhw64.so.1` / `libmfx-gen.so.1.2`、`libamfrt64.so.1`、`libnvidia-encode.so.1` / `libcuda.so.1` を確認しました。VA-API の実ドライバーは `LIBVA_DRIVERS_PATH`、QSV の GPU 実装・AMF はシステムの共有ライブラリ探索と `ldconfig` を通します。実機の永続ボリュームに保存済みの FFmpeg の版・ロード結果は未取得のため、その実物についてはホストで確認が必要です。

BtbN の [配布ポリシー](https://github.com/BtbN/FFmpeg-Builds#release-retention-policy)では通常の日次ビルドは直近14件、月末ビルドは2年間保持されます。今回は [2026年9月30日版](https://github.com/BtbN/FFmpeg-Builds/releases/tag/autobuild-2026-09-30-13-08)を固定していますが、その URL が永久に使えるわけではありません。将来の再ビルドでは取得可否とチェックサムを確認し、意図して更新してください。`gpl` ビルドや AMD / NVIDIA 等の各配布物はそれぞれのライセンスに従います。取得元のライセンス・ビルド情報を保持し、配布時の条件は採用した実物で確認します。

## 実ビルド前に確認したこと

Dockerfile で要求する apt パッケージ63種類について、Ubuntu noble / Intel PPA / AMD の配布 index に候補があることを確認しました。KonomiTV の downloader / runtime で使う5種類も追加確認し、Dockerfile と共通スクリプトの直接指定は合計68種類です。`aria2` は noble universe (`1.37.0+debian-1build3`)、`unzip` は noble main (`6.0-28ubuntu4`) に存在します。`cuda-nvrtc-12-8=12.8.61-1` と `libnpp-12-8=12.3.3.65-1` は [NVIDIA の Ubuntu 24.04 amd64 index](https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/Packages.gz)、`google-chrome-stable` は [Google の amd64 index](https://dl.google.com/linux/chrome/deb/dists/stable/main/binary-amd64/Packages.gz) に存在します。Intel legacy / IGC の3つの deb は実物を取得して SHA-256 を照合し、現行 OpenCL と legacy1 が別 ICD ファイルを持つことを確認しました。noble の `libmfx1` の実物には dispatcher の `libmfx.so.1` と旧 GPU 実装の `libmfxhw64.so.1` が含まれます。

選定した BtbN の配布実物は、ARIB / libass / 各 GPU encoder のビルド情報、最大 GLIBC 要求 2.28、システムの `libva.so.2` を動的ロードする構成を確認しました。これはパッケージ名だけからの推測を減らすための監査です。apt の全依存解決、Docker の全 stage ビルド、GPU 初期化の成功までは確認できていません。

固定した Intel 配布物は [compute-runtime 24.35.30872.36](https://github.com/intel/compute-runtime/releases/tag/24.35.30872.36) と [IGC 1.0.17537.24](https://github.com/intel/intel-graphics-compiler/releases/tag/igc-1.0.17537.24)、AMD の候補確認元は [AMDGPU 6.4.4 noble index](https://repo.radeon.com/amdgpu/6.4.4/ubuntu/dists/noble/proprietary/binary-amd64/Packages.gz) と [ROCm 6.4.4 noble index](https://repo.radeon.com/rocm/apt/6.4.4/dists/noble/main/binary-amd64/Packages.gz)です。

## Compose のデバイスと権限

| 選択 | 共通 override | 各エンコードサービスへ渡すもの |
| --- | --- | --- |
| `none` | なし | GPU デバイスなし。ソフトウェア方式を実行検証 |
| `intel` | `compose.intel.yaml` | `/dev/dri`、`RENDER_GID` |
| `amd` | `compose.amd.yaml` | `/dev/dri`、`VIDEO_GID`、`RENDER_GID`。`/dev/kfd` がある場合だけ `compose.amd.kfd.yaml` を追加 |
| `nvidia` | `compose.nvidia.yaml` | NVIDIA device reservation、count all、compute / utility / video |

共通 override の対象は recisdb-proxy、EPGStation、KonomiTV です。Amatsukaze 有効時に限り `compose.amatsukaze.yaml` と対応する `compose.amatsukaze.{intel,amd,nvidia}.yaml` を追加します。GPU override だけで無効な追加サービスを作らない構成です。

`setup.sh` は選択した GPU ベンダーに対応する render node の所有 GID を調べ、`RENDER_GID` / `VIDEO_GID` を `.env` へ保存します。AMD は `/dev/kfd` がある場合だけ `compose.amd.kfd.yaml` と、Amatsukaze 有効時の `compose.amatsukaze.amd.kfd.yaml` を追加します。ない場合は警告して `/dev/dri` のみで続けます。KFD は ROCm/OpenCL 用の任意デバイスです。チューナー用 `compose.tuners.yaml` のデバイス・補助 GID と GPU 設定は Compose の merge で共存します。

EPGStation の root から録画用 UID への移行は `setpriv --keep-groups` を使い、Compose の `group_add` を保持します。Amatsukaze の通常起動はデバイス所有 GID を実行ユーザーに追加します。プローブも Amatsukaze と該当する EPGStation について指定 UID / GID で実行します。

AMD の基本 override は `/dev/dri` のみです。`/dev/kfd` がある環境では追加 overlay が ROCm/OpenCL 用に KFD を渡します。VA-API / AMF は KFD がなくても判定します。

## セットアップと設定保全

GPU の検出は `/sys/class/drm/*/device/vendor` と `lspci -nn` のディスプレイデバイスから行います。候補が複数なら NVIDIA → AMD → Intel の順です。`GPU=none|intel|amd|nvidia` が明示指定です。既存セットアップの選択も初期値として保持します。

`.env.example` の `GPU=auto` は未選択を示します。setup.sh が検出・選択後に具体的な値を保存します。`--reconfigure` では検出をやり直し、保存済み選択を質問の既定値にします。`GPU=amd ./setup.sh --reconfigure` のように上書きできます。

通常セットアップではビルド後、各サービスの一時コンテナで H.264 / HEVC を別々に検証します。EPGStation は実際の `enc.js` プリセット、recisdb-proxy は生成するプレビュープロファイルの引数も使います。KonomiTV / Amatsukaze の Rigaya ツールは raw 720p を入力して短い出力ファイルを作り、終了状態とファイルの存在を確認します。ホスト上の別 FFmpeg の成功を、コンテナ内の成功として扱いません。

| サービス | GPU 候補と失敗時の経路 | 設定反映 |
| --- | --- | --- |
| EPGStation | Intel: QSV、AMD: AMF、NVIDIA: NVENC。各候補の後に software | 既存 `stream` / `encode` を保ち、既存 H.264 コマンドを変えない。`hardwareEncoder` は QSV=`qsv`、AMF=`vce`、NVENC=`nvenc`、software=`auto`。HEVC は独立プローブ成功時だけ追加 |
| recisdb-proxy | Intel: QSV → VA-API、AMD: AMF → VA-API、NVIDIA: NVENC。最後に software | 初期の `preview-h264` / `preview-4k` の未編集行のみ更新 |
| KonomiTV | GPU に対応する QSVEncC / VCEEncC / NVEncC。失敗時に自身の FFmpeg | `general.encoder` を反映 |
| Amatsukaze | `qsvencc` / `vceencc` / `nvencc`。失敗時に x264 | `EPGStation.profile` の EncoderType を反映 |

EPGStation の同時数は hardware で最大2、software で CPU 数の半分を基準に最大4です。実録画・視聴が同時に走る条件で調整してください。短いプローブは長時間の実効速度や同時セッション上限を測定するベンチマークではありません。

EPGStation のイメージは `/app/config/enc.js.template` を `/app/config/enc.js` に複製します。プローブはこの実ファイルを使い、`HWENCODER_H264` / `HWENCODER_HEVC` に固定バックエンドのエンコーダ名を渡して `h264` / `hevc` の汎用プリセットを実行します。設定では `hardwareEncoder` を指定して EPGStation の実行時自動選択を維持します。AMD の設定値 `vce` が runtime で AMF を選びます。

設定ファイルの追跡は `config/.generated-configs.json` の内容ハッシュで行います。追跡済みの生成物か、元テンプレートと完全一致するファイルだけを退避して更新し、それ以降の手動変更を含むファイルは保持します。ファイルの inode を保ち、既存の bind mount を壊さないよう書き込みます。recisdb-proxy の更新 Web API には条件付き更新がなく、読み取りと POST の間の手動編集を保護できないため、反映は SQLite の writer lock、変更前 JSON バックアップ、既知の初期プロファイルとの完全一致確認を使います。ID、参照、実行ファイルのパス、管理者編集済みの行を変更しません。

`config/gpu-probe.json` にサービスごとの判定、`config/gpu-probe-log.json` に実行コマンドと出力を保存します。両方とも mode 0600 です。H.264 も使えなければ設定を維持します。手動設定を保持した場合、プローブの成功はその手動設定への適用を意味しません。更新を適用する場合の再作成コマンドも表示します。

プレビュープロファイルの DB 更新は新しく始めるプレビューセッションから使われます。確認した recisdb-proxy `feature/proxy` の `badd538` では、`database/encode_profile.rs` (435–445行) がプロファイル取得時に DB を読み、`web/stream.rs` (639–692行、985–1005行) が新しいリクエストごとに設定を読み直します。既存セッションは保持中の設定を使うため、切断・再接続が必要です。書き込み API (`web/api/configs.rs` 687–730行) に更新条件指定がなく、読み取り後の管理者編集を条件付き更新で保護できないため、GPU 設定反映では DB writer lock とバックアップを使います。自動でサービスを再起動せず、進行中の視聴を止めないようにしています。設定反映後に既存セッションも切り替える場合は、視聴を終えてから表示された `docker compose restart recisdb-proxy` を実行してください。

`--no-start` は一時プローブコンテナも起動しません。`--reconfigure` はビルドや常駐サービスの起動を行いませんが、既存イメージを使った一時プローブは実行します。

## x86_64 Linux ホストでのビルド

以下はそのホストで行う検証用の操作です。初期セットアップは `.env`、`config/`、`data/` を準備します。既存環境では先に現在の設定・録画予定・空き容量を確認し、作業対象のチェックアウトを使用します。

```sh
uname -m
docker version
docker compose version
lspci -nn
ls -ln /dev/dri /dev/kfd
python3 scripts/gpu_setup.py detect
```

AMD を含め、`/dev/kfd` が存在しないこと自体は問題ありません。KFD がない場合は ROCm/OpenCL 用 overlay を省略します。NVIDIA はホストの `nvidia-smi` と Toolkit の設定を確認します。

```sh
nvidia-smi
docker info --format '{{json .Runtimes}}'
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu24.04 nvidia-smi
```

新規検証環境の Intel 例です。AMD / NVIDIA / software は `GPU` の値を置き換えます。`KONOMITV_SOURCE` は今回の Dockerfile 修正を含む実際のパスにしてください。

```sh
GPU=intel KONOMITV_SOURCE=/absolute/path/to/KonomiTV \
  ./setup.sh --no-build --no-start --no-scan
docker compose config --quiet
docker compose build --no-cache recisdb-proxy epgstation konomitv
```

有効にしたオプションサービスも同じチェックアウトからビルドします。無効サービスを列挙すると Compose がエラーにするため、実際の構成にあるサービスだけ指定します。

```sh
docker compose config --services
docker compose build --no-cache amatsukaze edcb boncasrelay https-gateway
```

期待結果は各 stage の成功、実行可能ファイルの配置、パッケージ依存解決です。Dockerfile が外部リポジトリを clone するため、最新の指定ブランチを取り込み直す検証では `--no-cache` を使います。アプリケーションの参照値を変更する操作はこの手順に含めません。

## 一括プローブと単独サービスの切り分け

生成済み `.env` の `COMPOSE_FILE` が検証する GPU と一致している状態で実行します。`--gpu` だけでは Compose のデバイス割当は変わりません。

```sh
python3 scripts/gpu_setup.py probe --root "$PWD" --env "$PWD/.env" --gpu intel
python3 -m json.tool config/gpu-probe.json
python3 -m json.tool config/gpu-probe-log.json
```

これは設定反映を含む本番と同じ判定経路です。recisdb-proxy のプレビュー判定には起動済みサービス、DB と有効な API 認証情報が必要です。初回は先に起動と WebUI のプレビュー自動セットアップを完了させ、その後に再判定します。通常の `setup.sh` は起動後にもプレビューだけを再判定します。

```sh
docker compose up -d
docker compose ps
# recisdb-proxy のプレビュー自動セットアップ完了後
python3 scripts/gpu_setup.py probe --root "$PWD" --env "$PWD/.env" --gpu intel --preview-only
```

単独サービスだけを調べる場合、次の関数は同じ `Probe` 実装を呼び、設定ファイルや DB のプロファイルを更新せず結果と診断ログを標準出力へ出します。`recisdb-proxy` では実行中のプレビュー設定を読み取ります。

```sh
gpu_probe_service() {
  python3 - "$1" "$2" <<'PY'
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path('scripts').resolve()))
import gpu_setup

root = Path.cwd()
service, gpu = sys.argv[1:]
render = gpu_setup.module('gpu_render_manual', 'render-config.py')
env = render.read_env(root / '.env')
probe = gpu_setup.Probe(root, env, 'docker')
if service in ('konomitv', 'amatsukaze'):
    result = probe.rigaya(service, gpu)
elif service == 'epgstation':
    node = gpu_setup.selected_render_node(gpu)
    result = probe.ffmpeg(service, gpu, render_node=node)
elif service == 'recisdb-proxy':
    preview = gpu_setup.module('gpu_preview_manual', 'preview-profiles.py')
    config = preview.read_preview_config(root, env, 'docker')
    node = gpu_setup.selected_render_node(gpu)
    result = probe.ffmpeg(service, gpu, config['command_path'], node)
else:
    raise SystemExit('Unknown service')
print(json.dumps({'result': result, 'logs': probe.logs}, ensure_ascii=False, indent=2))
raise SystemExit(0 if result['h264'] else 1)
PY
}

gpu_probe_service epgstation intel
gpu_probe_service recisdb-proxy intel
gpu_probe_service konomitv intel
gpu_probe_service amatsukaze intel
```

最後の引数は `amd` / `nvidia` / `none` に変更できます。Amatsukaze は有効時だけ実行します。期待する結果は `h264: true` と、実際に選択された `backend` / `encoder` です。GPU を選んでも software に落ちた場合は GPU 成功ではありません。`hevc: false` は H.264 の失敗とは別です。個々の失敗出力を確認してから追加設定を判断してください。

直接コマンドを確認するための EPGStation の Intel QSV 最小例です。これ単独では実際のプリセットまで検証できないため、一括プローブと合わせて使います。

```sh
docker compose run --rm --no-deps --no-build -T --entrypoint /bin/sh epgstation -ec \
  'ffmpeg -hide_banner -loglevel error -nostdin -f lavfi -i testsrc2=size=1280x720:rate=30 -t 1 -an -vf format=nv12 -c:v h264_qsv -preset veryfast -b:v 2000k -f null -'
```

Rigaya の Linux 実行名は KonomiTV の `/code/server/thirdparty/QSVEncC/QSVEncC.elf` 等と、Amatsukaze の `qsvencc` / `nvencc` / `vceencc` で異なります。`--raw --input-res 1280x720 --fps 30 -i -` は [QSVEnc 8.33](https://github.com/rigaya/QSVEnc/blob/8.33/QSVEncC_Options.en.md#--raw)、[NVEnc 9.38](https://github.com/rigaya/NVEnc/blob/9.38/NVEncC_Options.en.md#--raw)、[VCEEnc 9.21](https://github.com/rigaya/VCEEnc/blob/9.21/VCEEncC_Options.en.md#--raw)の対応オプションです。Amatsukaze のプロファイル enum は `QSVEnc` / `NVEnc` / `VCEEnc`、software は `x264` です。

## 実機検証で残る確認

ローカル検証では `make test` 全体、GPU 判定の11テスト、プレビュー DB の14テスト、Compose CLI の128構成とマージ順序、shellcheck、bash 構文、`git diff --check` を確認します。Compose は GPU 4 種と KFD 有無を組み合わせるため、AMD 以外の構成は KFD 有無によって変わりません。既存の stat スタブと Relay の絶対パス依存はテスト環境側を補正しています。Lua インタープリターがない場合、ダッシュボード Lua ラッパーの実行確認はスキップされ、静的検査のみです。これらは Docker ビルドや GPU 動作の代わりにはなりません。

GPU プローブは DRM render node の PCI vendor ID を照合し、選択ベンダーに属する node だけを VA-API とプレビュープロファイルに渡します。混在 GPU 環境で別ベンダーの node にフォールバックしません。EPGStation の upstream 設定には `renderD128` 固定の箇所があるため、選択 node が異なる場合は警告を確認し、そのプリセットの node 指定が使われる状況に注意してください。

```sh
for node in /sys/class/drm/renderD*; do
  printf '%s ' "$node"
  readlink -f "$node/device"
  cat "$node/device/vendor"
done
```

プローブ後は表示された対象サービスを再作成し、アプリケーション側から実データを確認します。EPGStation は H.264 / 有効時 HEVC の録画後エンコードとライブ・録画再生、recisdb-proxy は通常・4K プレビュー、KonomiTV はライブ視聴、Amatsukaze は EPGStation 経由の実ジョブを確認してください。ARIB 字幕、音声、シーク、実時間以上の処理速度、同時録画との負荷を確認します。実放送やチューナー未接続の結果は、GPU 合成動画テストと分けて記録します。

この変更の段階では、実機ビルド成功、実 GPU の対応世代、AMD proprietary ランタイムの同居、Intel の旧世代 QSV / OpenCL、ARIB 字幕を含む実放送の一連の処理は未確認です。ホストでのビルド・プローブ・実ジョブの結果を追記してから、その環境の動作確認済みとします。
