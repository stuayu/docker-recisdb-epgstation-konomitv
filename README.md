# docker-recisdb-epgstation-konomitv

この構成は Linux 上の Docker Compose でテレビ放送を録画・視聴するシステムです。
recisdb-proxy がチューナーを管理し、Mirakurun 互換 API で EPGStation と KonomiTV に番組情報を渡します。
B-CAS / ACAS カードは BonCasRelay から LAN 経由で利用します。

```mermaid
flowchart LR
  subgraph card[カードホスト Linux / macOS / Windows]
    cas[B-CAS / ACAS カードとカードリーダー] --> relay[BonCasRelay :6900]
    web[カードホストのブラウザー] --> relayui[BonCasRelay Web 設定 :6980]
  end
  subgraph host[録画ホスト Linux + Docker]
    tuner[チューナー /dev] --> proxy[recisdb-proxy :40080]
    relay <-->|BonCasLink 互換| proxy
    proxy --> epg[EPGStation :8888]
    proxy --> tv[KonomiTV HTTPS :7000]
    proxy --> edcb[EDCB 任意 / WebUI :5510]
    epg --> db[MariaDB 標準 :3306]
    edcb --> edcbrec[/recorded/edcb]
    epg -->|AddTask / TCP :32768| ama[Amatsukaze 任意 / WebUI :32769]
    recordings[共有 /recorded] <--> epg
    recordings <--> ama
  end
  browser[LAN 内ブラウザー] --> proxy
  browser --> epg
  browser --> tv
  browser --> ama
  browser --> gateway[Akebi HTTPS :40443 / :8443]
```

## 必要なもの

- Linux 録画ホスト。Ubuntu 24.04 LTS または Debian 12 を推奨します。
- Docker Engine と Compose v2。初回ビルドに数 GB の空きディスク容量が必要です。メモリは 8 GB 以上を推奨します。
- recisdb-proxy-rs が対応するチューナーと Linux ドライバー。例: PLEX PX-W3U4 / PX-Q3U4 / PX-MLT 系、DTV02A など。型番・ドライバー版で対応状況が異なります。`/dev/px4video*`、`/dev/pt3video*`、`/dev/pxmlt5video*`、`/dev/isdb2056video*` または `/dev/dvb/adapterN` のノードを使います。`isdb6014video*` は参照 README に対応記載がありません。
- B-CAS または ACAS カードとカードリーダー。カードホストと録画ホストは同じ LAN に置いてください。カードホストは録画ホストと同じマシンでも構いません。
- KonomiTV の Dockerfile を含むソース。セットアップが `stuayu/KonomiTV` を取得できます。

## ホスト機側の準備

### カードホスト (BonCasRelay とカードリーダー)

カードホストは Linux / macOS / Windows のいずれでも構いません。PC/SC は、アプリがカードリーダーを利用するための OS 共通 API です。カードリーダーの USB 接続後、OS 側で認識することを確認してください。

#### Linux (Ubuntu / Debian): PC/SC

```bash
sudo apt update
sudo apt install -y pcscd libpcsclite1 libccid pcsc-tools
sudo systemctl enable --now pcscd
pcsc_scan
```

`pcsc_scan` にリーダー名とカード挿入状態が出ることを確認します。終了は `Ctrl+C`。パッケージと `pcscd` の手順は recisdb-proxy-rs README の PC/SC 節に基づいています。

#### macOS: PC/SC

macOS 標準の PC/SC (CryptoTokenKit) を使います。追加の `pcscd` は導入しません。BonCasRelay をビルドした後、次でリーダーを列挙します。

```bash
boncasrelay --list-readers
```

出力にカードリーダー名があることを確認します。カードを挿しても出ない場合は、カードリーダーの USB 接続と macOS のシステム情報を確認してください。

#### Windows: Smart Card サービス

PowerShell で Smart Card サービス (`SCardSvr`) を確認します。

```powershell
Get-Service SCardSvr
```

停止中なら管理者 PowerShell で起動します。

```powershell
Start-Service SCardSvr
```

BonCasRelay をビルド後、`boncasrelay.exe --list-readers` でリーダー名を確認します。

#### BonCasRelay をソースからビルド

BonCasRelay の GitHub Releases にビルド済み配布ファイルはまだありません。公開後はリリースからのダウンロード手順へ置き換える予定です。現状は Rust stable / Cargo と各 OS のビルド環境を入れ、ソースからビルドします。共通のビルド手順は [BonCasRelay README](https://github.com/stuayu/BonCasRelay#インストールとビルド) を参照してください。

Linux (Ubuntu / Debian):

```bash
sudo apt update
sudo apt install -y build-essential pkg-config libpcsclite-dev pcscd libpcsclite1 libccid
sudo systemctl enable --now pcscd
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
git clone https://github.com/stuayu/BonCasRelay.git
cd BonCasRelay
cargo build --release --features tray
sudo install -m 0755 target/release/boncasrelay /usr/local/bin/boncasrelay
```

macOS: Xcode Command Line Tools と Rust stable を用意します。Rust は [rustup.rs](https://rustup.rs/) の macOS 手順に従います。

```bash
xcode-select --install
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
git clone https://github.com/stuayu/BonCasRelay.git
cd BonCasRelay
cargo build --release --features tray
sudo install -m 0755 target/release/boncasrelay /usr/local/bin/boncasrelay
```

Windows: [rustup.rs](https://rustup.rs/) から Rust stable を導入し、Visual Studio Build Tools の C++ ワークロードを追加してから PowerShell で実行します。

```powershell
git clone https://github.com/stuayu/BonCasRelay.git
cd BonCasRelay
cargo build --release --features tray
```

実行ファイルは `target\release\boncasrelay.exe` にできます。トレイを使わない場合は `--features tray` の代わりに `--no-default-features` を指定できます。Linux / macOS は `target/release/boncasrelay` です。

#### BonCasRelay 起動・常駐化

録画ホストの IP のみを許可します。以下の IP は実際の録画ホスト IP に置き換えてください。

```bash
boncasrelay --allow 192.168.1.20/32
```

既定のカード通信は TCP 6900、Web 設定は `http://127.0.0.1:6980/` です。Web 設定画面はカードホスト自身から開き、外部インターフェースへ公開しないでください。Web UI の認証はありません。

- Linux systemd user service: BonCasRelay リポジトリのルートで unit と INI を配置します。

  ```bash
  mkdir -p ~/.config/systemd/user ~/.config/boncasrelay
  cp contrib/systemd/boncasrelay.service ~/.config/systemd/user/
  cp contrib/boncasrelay.ini ~/.config/boncasrelay/boncasrelay.ini
  ```

  `~/.config/boncasrelay/boncasrelay.ini` の `[General] Allow=` を録画ホストの `/32` に変更し、`systemctl --user daemon-reload && systemctl --user enable --now boncasrelay` を実行します。unit は `/usr/local/bin/boncasrelay --config ...` を実行します。
- macOS launchd: BonCasRelay リポジトリのルートで plist と INI を配置します。

  ```bash
  mkdir -p ~/Library/LaunchAgents "$HOME/Library/Application Support/BonCasRelay"
  cp contrib/launchd/io.github.stuayu.boncasrelay.plist ~/Library/LaunchAgents/
  cp contrib/boncasrelay.ini "$HOME/Library/Application Support/BonCasRelay/boncasrelay.ini"
  ```

  INI の `[General] Allow=` を録画ホストの `/32` に変更し、plist のバイナリパスを確認して `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/io.github.stuayu.boncasrelay.plist` を実行します。
- Windows: `Win+R` → `shell:startup` を開き、`boncasrelay.exe --tray` のショートカットを置きます。`%APPDATA%\BonCasRelay\boncasrelay.ini` の `[General] Allow=` に録画ホスト IP を設定します。
- Linux デスクトップ自動起動: `contrib/autostart/boncasrelay.desktop` を `~/.config/autostart/` に置きます。

#### カードホストのファイアウォール

Linux で UFW を使う場合、カード通信ポートを録画ホスト IP からだけ許可します。

```bash
sudo ufw insert 1 allow from 192.168.1.20 to any port 6900 proto tcp
sudo ufw deny 6900/tcp
```

macOS の「システム設定 → ネットワーク → ファイアウォール」では BonCasRelay の着信を LAN 内に限定してください。アプリ単位の macOS ファイアウォールは送信元 IP 制限を指定しないため、送信元制限はルーター/VLAN 側でも行います。

Windows 管理者 PowerShell:

```powershell
New-NetFirewallRule -DisplayName 'BonCasRelay TCP 6900' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 6900 -RemoteAddress 192.168.1.20
```

TCP 6980 の Web 設定画面用ルールは作らないでください。BonCasLink 互換通信は平文・無認証です。

### 録画ホスト (Linux + Docker)

#### Docker Engine と Compose v2

[Docker Engine 公式手順](https://docs.docker.com/engine/install/)を使います。Ubuntu では公式 apt リポジトリの手順を以下に示します。

```bash
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
```

ログアウト・再ログイン後、`docker compose version` を確認します。`docker` グループは root 相当の権限を持つため、信頼するユーザーだけを追加してください。

#### px4_drv チューナードライバー

recisdb-proxy-rs は Linux で px4_drv のデバイスノードを使います。Ubuntu / Debian では px4_drv README が DKMS 版 Debian package を推奨し、パッケージ導入時にファームウェアも配置します。以下は参照 README にある v0.6.1 の例です。対応機種と最新版は [px4_drv README](https://github.com/tsukumijima/px4_drv#インストール-linux) を先に確認してください。

```bash
sudo apt update
sudo apt install -y wget build-essential dkms linux-headers-$(uname -r)
wget https://github.com/tsukumijima/px4_drv/releases/download/v0.6.1/px4-drv-dkms_0.6.1_all.deb
sudo apt install -y ./px4-drv-dkms_0.6.1_all.deb
sudo modprobe px4_drv
lsmod | grep -e '^px4_drv'
ls /dev/px4video*
```

DKMS はカーネル更新後にモジュールを再ビルドする仕組みです。README の依存は gcc / make / kernel headers / dkms。DKMS package の場合、ファームウェアは自動導入されます。手動導入ではファームウェア抽出が別途必要なため、上記 README の手順を使います。

recisdb-proxy コンテナは root ではなく動くため、udev でデバイスを `video` グループへ公開します。以下は recisdb-proxy-rs README の例です。

```bash
sudo tee /etc/udev/rules.d/99-px4video.rules >/dev/null <<'RULES'
KERNEL=="px4video*",     GROUP="video", MODE="0660"
KERNEL=="pxmlt*video*",  GROUP="video", MODE="0660"
KERNEL=="isdb*video*",   GROUP="video", MODE="0660"
KERNEL=="pt*video*",     GROUP="video", MODE="0660"
RULES
sudo udevadm control --reload-rules
sudo udevadm trigger
sudo usermod -aG video "$USER"
```

ログアウト・再ログインし、`ls /dev/px4video*` などでノードを確認します。機種によりノード名は異なります。対応外の機種では px4_drv README を参照してください。

#### GPU (任意)

Intel / AMD はホストに `/dev/dri/renderD128` 等があることを確認します。デバイスの group が `render` の場合は、その GID でアクセスできることが必要です。setup.sh は `render` group GID を `VIDEO_GID` に設定します。KonomiTV Dockerfile には Intel Media Driver (`intel-media-va-driver-non-free` 等) が含まれるため、Intel QSV / VAAPI 用ユーザー空間パッケージをホストへ重ねて入れる必要はありません。AMD VCE は [KonomiTV README の AMDGPU-PRO driver 節](https://github.com/stuayu/KonomiTV#linux---vceencc)を確認してください。

```bash
ls -l /dev/dri/renderD*
getent group render
```

NVIDIA は先にホスト NVIDIA driver を導入し、`nvidia-smi` が動くことを確認します。Ubuntu では NVIDIA driver の [Ubuntu package manager 手順](https://documentation.ubuntu.com/server/how-to/graphics/install-nvidia-drivers/)を使えます。続けて [NVIDIA Container Toolkit 公式手順](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)に従い、Ubuntu / Debian の apt repository と Toolkit を設定します。

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends ca-certificates curl gnupg2
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update
sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
docker info --format '{{json .Runtimes}}'
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi
```

`docker info` に `nvidia` runtime があり、最後のコンテナから GPU 情報が出れば確認完了です。KonomiTV の Dockerfile は CUDA 12.8 base を使います。

#### 録画ホストのファイアウォール

Compose は HTTP 40080 / 8888、HTTPS 40443 / 8443、KonomiTV 7000、EDCB 有効時は HTTP 5510 / HTTPS 8553 を全ホストアドレスへ publish します。Docker 公開 port は UFW の通常 INPUT ルールを迂回するため、UFW の allow/deny だけで制限できるとは限りません。まずルーター/VLAN ACL で LAN からだけ許可してください。ホストの iptables backend を使う場合は Docker の `DOCKER-USER` chain を使います。次は `eno1` を実際の外向き NIC、CIDR を実 LAN に置き換える例です。

```bash
for port in 40080 8888 40443 8443 7000 5510 8553; do
  sudo iptables -I DOCKER-USER -i eno1 -p tcp -m conntrack --ctorigdstport "$port" ! -s 192.168.1.0/24 -j DROP
done
```

Nftables backend では対応する Docker nftables firewall 手順に合わせてください。Docker は UFW と公開 port のフィルタリングが互換でないと説明しています: [Docker firewall documentation](https://docs.docker.com/engine/network/packet-filtering-firewalls/)。
この例は IPv4 用です。ホストで IPv6 を使う場合は IPv6 の公開 port もルーターまたは `ip6tables` / nftables で同じ LAN 制限を設定してください。

## アクセス方法

HTTP 直通は従来どおり使えます。HTTPS 経路を有効にすると、Akebi gateway のポートごとに転送先を選びます。

| システム | HTTP | HTTPS |
| --- | --- | --- |
| recisdb-proxy | `http://<録画ホストIP>:40080/` | `https://<IPをハイフン区切り>.local.konomi.tv:40443/` |
| EPGStation | `http://<録画ホストIP>:8888/` | `https://<IPをハイフン区切り>.local.konomi.tv:8443/` |
| EDCB (任意) | `http://<録画ホストIP>:5510/E3/` | `https://<IPをハイフン区切り>.local.konomi.tv:8553/E3/` |
| MariaDB | Compose 内 `mariadb:3306` のみ | 対象外 |
| Amatsukaze (任意) | `http://<録画ホストIP>:32769/` | 対象外 |
| KonomiTV | 対象外 | `https://<IPをハイフン区切り>.local.konomi.tv:7000/` |

ポート番号で転送先を切り替えます。KonomiTV は内蔵 Akebi を使い、HTTP 直通は対象外です。本体 Uvicorn がコンテナ内 `127.0.0.77` だけで待ち受け、HTTP 直通にはフォーク改造が必要です。

HTTPS gateway は `.env` の `COMPOSE_FILE` に `compose.https.yaml` が含まれる場合だけ起動します。setup.sh の既定は有効です。Akebi は SNI の `*.local.konomi.tv` に対する証明書を Keyless Server から取得し、TLS 終端後に内部 HTTP へ転送します。HTTP から HTTPS への自動リダイレクトはありません。

既定の `akebi.konomi.tv` は KonomiTV 開発者が運営する Keyless Server です。停止や運用方針変更の影響を受けます。自前の Keyless Server に切り替える場合は `.env` の `AKEBI_KEYLESS_SERVER_URL` を変更してください。構築方法は [Akebi README](https://github.com/tsukumijima/Akebi) を参照してください。

`*.local.konomi.tv` の名前解決は DNS Rebinding Protection に遮断される場合があります。ルーターの保護設定を調整するか、端末が公開 DNS を使うよう設定してください。LAN 限定アクセスを維持する場合は、DNS 設定とファイアウォールを合わせてください。

## かんたんセットアップ (おすすめ)

### 1. このリポジトリを取得してセットアップ

```bash
git clone https://github.com/stuayu/docker-recisdb-epgstation-konomitv.git
cd docker-recisdb-epgstation-konomitv
./setup.sh
```

対話端末に whiptail または dialog があれば画面で選択できます。ない場合は Debian / Ubuntu で導入を確認し、拒否した場合は文字入力へ戻ります。質問には既定値が表示されます。BonCasRelay のホスト名/IP、録画先、GPU、EDCB、Amatsukaze の利用を選びます。通常の初回構成では Enter で進められます。チューナーが未検出でも続行でき、ドライバー導入後に `make tuners` を実行できます。ビルドと起動を含めず設定だけ行う場合は `./setup.sh --reconfigure` を使います。

### 2. ブラウザーで初期設定

1. recisdb-proxy は `http://<録画ホストIP>:40080/` または HTTPS 有効時の `https://<IPをハイフン区切り>.local.konomi.tv:40443/` を開きます。初回 token は `docker compose logs recisdb-proxy` の `Web API auth token:` 行です。セットアップがログから表示できた場合はその token を使ってください。
2. recisdb-proxy の「BonDriver」画面で検出されたチューナーデバイスを登録し、チャンネルスキャンを実行します。チューナーパスは `/dev/px4video0` など実在する名前を使います。
3. EPGStation は `http://<録画ホストIP>:8888/` または HTTPS 有効時の `https://<IPをハイフン区切り>.local.konomi.tv:8443/` を開き、番組表から予約します。EPGStation の Mirakurun 接続先は内部ネットワーク上の `http://recisdb-proxy:40080/mirakurun/` です。
4. KonomiTV (`https://<IPのドットをハイフンに変換>.local.konomi.tv:7000/`) を開いて初期設定し、チャンネル一覧からライブ視聴します。例: IP が `192.168.1.20` なら `https://192-168-1-20.local.konomi.tv:7000/`。KonomiTV は Akebi による HTTPS が必要で、IP のドットをハイフンにした `*.local.konomi.tv` が正規 URL です。DNS Rebinding Protection が有効なルーターでは名前解決を止められることがあります。その場合はルーターの保護設定を調整するか、公開 DNS を使います。初回起動には外部 DNS / Keyless サーバーとの通信も必要です。KonomiTV の URL 仕様と DNS 問題は [KonomiTV README](https://github.com/stuayu/KonomiTV#httpsaa-bb-cc-ddlocalkonomitv7000-の-url-について)を参照してください。KonomiTV の Mirakurun backend は予約録画に対応しないため、予約は EPGStation または EDCB を使います。
5. EDCB 有効時は recisdb-proxy のスキャン完了後に `make edcb-chset` を実行し、`http://<録画ホストIP>:5510/E3/` を開きます。EDCB 自身によるチャンネルスキャンや接続設定の手編集は不要です。
6. 地デジ/BS のスクランブル放送で B25 復号、実際の予約録画と再生を確認します。4K は ACAS 対応構成と dantto4k が別途必要です。

## 手動セットアップ (経験者向け)

```bash
./setup.sh --reconfigure
make tuners
```

`.env` の `BONCAS_B25_HOST`、`BONCAS_B25_PORT`、`BONCAS_4K_HOST`、`BONCAS_4K_PORT`、`RECORDED_DIR`、`VIDEO_GID`、`KONOMITV_SOURCE` を環境に合わせます。BonCasRelay は APDU を判定して B-CAS / ACAS を既定の同じ 6900 番ポートへ振り分けるため、同じホスト・ポートを設定できます。`VIDEO_GID` はホストの `video` グループ ID です。

```bash
docker compose config
docker compose build
docker compose up -d
docker compose logs -f recisdb-proxy
```

`.env` の `COMPOSE_FILE` は Compose ファイルのコロン区切りです。標準は `compose.yaml:compose.tuners.yaml`。Intel は `:compose.intel.yaml`、NVIDIA は `:compose.nvidia.yaml`、EDCB は `:compose.edcb.yaml` を加えます。EDCB と HTTPS を併用するときは末尾に `:compose.edcb.https.yaml` も加えます。NVIDIA には NVIDIA Container Toolkit が必要です。MariaDB は標準で起動し、setup.sh がパスワードを自動生成します。

EPGStation の DB は MariaDB 固定です。設定ファイルは `setup.sh` が初回だけ `config/<サービス名>/` に生成します (テンプレートは `templates/` にあります)。既存のファイルは上書きしません。`BONCAS_B25_HOST` / `BONCAS_B25_PORT` は recisdb-proxy の設定へ、`BONCAS_4K_HOST` が空なら 4K 設定を省いて生成します。`.env` の値を後から変えた場合は、「設定ファイルの編集」の `make regen-config` を使ってください。

## 日々の操作

| 操作 | コマンド |
| --- | --- |
| 初回セットアップ | `make setup` |
| 状態と URL | `make status` |
| 起動 | `make up` |
| 停止 | `make down` |
| ログ | `make logs` または `docker compose logs -f recisdb-proxy` |
| チューナー再検出 | `make tuners` |
| EDCB チャンネル再取得 | `make edcb-chset` (EDCB の録画がないとき) |
| 再ビルド | `make build` |
| ソース更新・再ビルド・再起動 | `make update` |
| 録画先だけ変更 | `make storage` |
| 設定・テスト | `make config` / `make test` |
| 設定ファイルの再生成 | `make regen-config SERVICE=<名前>` |
| バックアップ・復元 | `make backup` / `make restore FILE=...` |

## よくある質問・トラブルシュート

| 症状 | 原因 | 対処 |
| --- | --- | --- |
| チャンネルが映らない | チャンネルスキャン未実施、受信状態、チューナー登録不備 | recisdb-proxy の BonDriver 画面でデバイス登録・スキャン。ログとアンテナ受信を確認 |
| B25 復号できない | BonCasRelay 未起動、接続元許可漏れ、カード未認識 | `BONCAS_B25_HOST:PORT` へ TCP 接続できるか確認。Relay の `--allow` と Web 設定のリーダー判定を確認 |
| チューナーが見えない | デバイスノードなし、udev 権限、生成 Compose が古い | `ls /dev`、`VIDEO_GID`、`make tuners`、`docker compose config` を確認 |
| KonomiTV が Mirakurun URL を拒否 | `/mirakurun/api/tuners` が Mirakurun 互換 `Server: Mirakurun/...` ヘッダーを返さない | recisdb-proxy の互換 API 応答と `http://recisdb-proxy:40080/mirakurun` を確認 |
| HTTPS 経路に接続できない | `compose.https.yaml` が `COMPOSE_FILE` にない、ポート競合、Keyless 通信失敗 | `.env` の Compose 構成と HTTPS ポート、`docker compose logs https-gateway` を確認 |
| HTTPS の証明書を取得できない | DNS / Keyless Server への接続不可、Keyless Server の停止 | 外部 DNS と `AKEBI_KEYLESS_SERVER_URL` を確認。自前サーバー利用時は URL を合わせる |
| HTTPS 名が DNS エラー | ルーターの DNS Rebinding Protection が `*.local.konomi.tv` を遮断 | ルーター設定を調整するか、端末の DNS に公開 DNS を指定 |
| KonomiTV で TLS / HTTPS エラー | IP 直打ち、HTTP URL、または特殊ホスト名以外を使用 | `https://<IPのドットをハイフンにした値>.local.konomi.tv:<KONOMITV_PORT>/` を開く |
| ビルドが失敗する | 容量不足、ネットワーク、ソース取得失敗 | `df -h` と Docker ログを確認。必要な空き容量を確保して再実行 |
| ポートが使用中 | 40080 / 8888 / 40443 / 8443 / 7000 を別アプリが使用 | `.env` の `RECISDB_WEB_PORT` / `EPGSTATION_PORT` / `RECISDB_HTTPS_PORT` / `EPGSTATION_HTTPS_PORT` / `KONOMITV_PORT` を変更し再作成 |
| 録画先に書き込めない | 保存先の権限または空き容量不足 | `RECORDED_DIR` の所有者、書き込み権限、空き容量を確認 |
| Compose 内から API に届かない | ホスト公開ポートとコンテナ内部ポートの混同 | コンテナ間は `http://recisdb-proxy:40080/mirakurun/` を使用 |

## セキュリティ

BonCasLink 互換通信は平文・無認証です。BonCasRelay は信頼できる LAN/VPN に限定し、`--allow` とファイアウォールで録画ホストだけ許可してください。BonCasRelay Web 設定画面は既定でループバック待受です。recisdb-proxy の Mirakurun API と各 Web UI をインターネットへ直接公開しないでください。

## 構成ファイル

| ファイル | 役割 |
| --- | --- |
| `compose.yaml` | recisdb-proxy、EPGStation、KonomiTV、標準の MariaDB サービス |
| `compose.tuners.yaml` | `make tuners` / setup が `/dev` から生成するチューナー公開設定 |
| `compose.intel.yaml` / `compose.nvidia.yaml` | KonomiTV コンテナへの GPU デバイス設定 |
| `compose.boncasrelay.yaml` | 任意の BonCasRelay と USB カードリーダー、限定サブネット |
| `compose.storage.yaml` | 複数録画先の追加マウント。セットアップが生成します |
| `compose.edcb.yaml` | 任意の EDCB と Material WebUI |
| `compose.edcb.https.yaml` | EDCB と HTTPS の両方が有効な場合の Akebi 経路 |
| `compose.amatsukaze.yaml` | 任意の Amatsukaze と EPGStation 連携設定 |
| `compose.amatsukaze.intel.yaml` / `compose.amatsukaze.nvidia.yaml` | Amatsukaze 有効時専用の GPU 設定 |
| `compose.https.yaml` | 任意の Akebi HTTPS gateway |
| `.env.example` | 初期環境変数の例 |
| `setup.sh` | 対話式初回セットアップ |
| `scripts/gen-tuners.sh` | チューナーデバイスから Compose ファイル生成 |
| `config/<サービス名>/` | setup.sh が初回生成する利用者編集用の設定 (recisdb-proxy / epgstation / konomitv / edcb / amatsukaze / boncasrelay / edcb-to-epgstation)。`backup/` に再生成前の退避ファイル |
| `templates/` | 設定ファイルの元になるテンプレート (`*.example`)。通常は編集しません |
| `scripts/` | 設定生成 (`render-config.py`)、バックアップ・復元 (`backup.sh` / `restore.sh`) など |
| `docker/` | 各コンテナの Dockerfile と起動処理 |
| `data/` | DB、ログ、サムネイル、一時ファイル、録画の永続保存先 |

Compose では `data/recisdb` に recisdb-proxy DB/ログ、`data/epgstation` に EPGStation の鍵・一時ファイル、`data/mariadb` に EPGStation DB、`data/epgstation-logs` にログ、`data/epgstation-thumbnail` にサムネイル、`data/epgstation-drop` に drop ログ、録画先に録画ファイルを保存します。KonomiTV DB/ログは `data/konomitv` / `data/konomitv-logs` です。

KonomiTV は bridge ネットワーク上で稼働し、Mirakurun 接続先は Compose DNS 名 `recisdb-proxy` です。ホスト公開ポート `${KONOMITV_PORT}:7000` がブラウザーからの入口です。録画ディレクトリはコンテナ内 `/host-rootfs/recorded` に読み取り専用で割り当てます。

recisdb-proxy の Web 認証は `config/recisdb-proxy/recisdb-proxy.toml` の `[web] auth_enabled = true` で有効です (初期値は `templates/recisdb-proxy/recisdb-proxy.toml.example`)。初回 token は DB に保存され、再起動後もログの `Web API auth token:` 行に表示されます。Mirakurun API の `/mirakurun/api/*` は token 認証対象外で、Compose 内の EPGStation / KonomiTV は `http://recisdb-proxy:40080/mirakurun/` を使います。

EPGStation は `config/epgstation/config.yml` を `/app/config/config.yml` としてマウントします。起動時には書き換えず、ファイルがなければ起動を止めて setup.sh の実行を促します。ログ設定ファイルがなければフォークの `*.sample.yml` から生成し、`/app/logs` はホストの `data/epgstation-logs` に保存します。

KonomiTV フォークは Akebi をコンテナ内 `0.0.0.0:server.port` で待ち受け、同じコンテナ内の `127.0.0.77:(server.port + 10)` の Uvicorn へ転送します。`<IPをハイフン区切り>.local.konomi.tv` はクライアントから Akebi に送る Host 名です。外向けの入口は Compose が公開する `7000` 番ポートです。設定は `config/konomitv/config.yaml` を `/code/config.yaml` としてマウントします (初期値は `templates/konomitv/config.yaml.example`)。KonomiTV はこのファイルへ設定を保存するため、読み書き可能でマウントしています。実装根拠はフォークの `server/KonomiTV.py` と `server/app/routers/MaintenanceRouter.py` です。


## 設定ファイルの編集

設定ファイルは `setup.sh` が初回だけ生成します。ファイルが既にあれば上書きしないため、ホストで編集した内容は次の起動や再セットアップで消えません。編集後は表の操作でサービスを再起動してください。

| サービス | ホスト上で編集するファイル | コンテナ内のパス | 内容 | 編集後の操作 |
| --- | --- | --- | --- | --- |
| recisdb-proxy | `config/recisdb-proxy/recisdb-proxy.toml` | `/data/recisdb-proxy.toml` | BonCasLink 接続先、Web 認証、DB パス。Web 画面の自動設定が preview 用のパスを書き換えることがあります | `docker compose restart recisdb-proxy` |
| EPGStation | `config/epgstation/config.yml` | `/app/config/config.yml` | DB 接続、エンコード設定、Amatsukaze 連携。DB パスワードを含むため権限は 600 です | `docker compose restart epgstation` |
| KonomiTV | `config/konomitv/config.yaml` | `/code/config.yaml` | KonomiTV サーバー設定。KonomiTV の設定画面からも保存されます | `docker compose restart konomitv` |
| EDCB (任意) | `config/edcb/*.ini`、`config/edcb/Setting/` の INI・ChSet | `/config/edcb/` から `/var/local/edcb/` へリンク | 録画・チューナー・WebUI 設定。予約・EPG は `data/edcb/` に保存します | `docker compose restart edcb` |
| Amatsukaze (任意) | `config/amatsukaze/{config,profile,avs,bat,drcs,JL,logo}/` | `/app/config/` など | Amatsukaze の設定。初回起動時に既定値を配置し、以後は上書きしません | `docker compose restart amatsukaze` |
| BonCasRelay (任意) | `config/boncasrelay/boncasrelay.ini` | `/config/boncasrelay.ini` | 待受・許可サブネット・カードリーダー。WebUI の保存も反映します | `docker compose restart boncasrelay` |
| EDCB-to-EPGStation (任意) | `config/edcb-to-epgstation/config.yml` | `/config/edcb-to-epgstation/config.yml` | API 接続先、登録方法、エンコード | 次の録画後実行から反映します |
| MariaDB | なし (`.env` の `MARIADB_*`) | なし | 接続情報は `.env` で管理します。`.env` のパスワードを変えても既存の DB データは変わりません | 対象外 |

`.env` の値 (BonCasRelay の接続先、Amatsukaze の有効/無効、DB パスワードなど) を後から変えたときは、該当サービスの設定ファイルを再生成します。

```bash
make regen-config SERVICE=epgstation    # edcb / amatsukaze / boncasrelay / edcb-to-epgstation も指定できます
```

再生成では、現在のファイルを `config/<サービス名>/backup/<ファイル名>.<日時>` に退避し、差分 (`diff -u` 形式) を表示してから置き換えます。確認は `y` で進みます。`--yes` 相当の非対話実行はできません (スクリプトでは `scripts/render-config.py regen --service <名前> --yes` を直接使います)。置き換えは同じファイルへの書き込みで行うため、コンテナのバインドマウントは保たれます。置き換え後は `docker compose restart <サービス名>` を実行してください。

既存の `config/epgstation/config.yml` に Amatsukaze の節がない状態で Amatsukaze を有効にした場合、setup.sh は自動で書き換えず、`make regen-config SERVICE=epgstation` の実行を案内します。

以前の構成 (`data/recisdb/recisdb-proxy.toml` や `config/config.yaml` など) からの移行は setup.sh が検出し、新しい場所へコピーして案内します。旧ファイルは削除しません。

## バックアップと復元

```bash
make backup                                          # backup/konomi-backup-YYYYmmdd-HHMMSS.tar.gz を作成
make restore FILE=backup/konomi-backup-YYYYmmdd-HHMMSS.tar.gz
```

`make backup` は `.env`、`config/`、`data/` を 1 つの tar.gz にまとめます。MariaDB は稼働中のコンテナから `mariadb-dump` で `db/epgstation.sql` を作ります。そのため `mariadb` が起動している必要があります。録画ファイル (`RECORDED_DIR`、既定 `data/recorded`) と `data/mariadb` の生ファイルは含めません。録画は別途バックアップしてください。

`.env` にはパスワードが含まれます。バックアップファイルは他人に渡さず、安全な場所に保存してください。

`make restore` は現在の `config/` と `data/` をアーカイブの内容で上書きする前に確認します。アーカイブの `.env` は、現在の `.env` がない場合だけ使います。ある場合は `.env.from-archive` として保存します。`compose.storage.yaml` は採用した `.env` から再生成し、アーカイブ内のファイルは `compose.storage.yaml.from-archive` に保存します。DB は mariadb を起動してダンプを取り込みます。既存の DB に同名のテーブルがあれば内容が置き換わります。

## 録画を自動で CM カット・エンコードする (Amatsukaze)

`./setup.sh` の初回質問「Amatsukaze を使いますか」は既定ではいです。初回選択後は `SETUP_AMATSUKAZE` に保存した有効・無効を再設定時の既定として保ちます。非対話では `AMATSUKAZE=yes ./setup.sh --yes`、無効にする場合は `AMATSUKAZE=no ./setup.sh --yes` と指定します。設定だけ変更する場合は `--reconfigure` を付け、後から `make build && make up` で反映します。既存 `.env` の誤った `EPGSTATION_REF=master` は `main` に移行します。カスタム ref は維持します。

Amatsukaze は `COMPOSE_FILE` に `compose.amatsukaze.yaml` を追加したときだけ起動します。手動構成では `AMATSUKAZE_VERSION=1.1.1.2`、`AMATSUKAZE_WEBUI_PORT=32769`、`RUN_UID` / `RUN_GID` を設定してください。UID/GID は `id -u` / `id -g` と録画先の所有者に合わせます。有効時は EPGStation と Amatsukaze が同じ UID/GID で実行されます。EPGStation は既存のアプリ設定・DB・ログ・サムネイル・drop の所有者を起動時に整えますが、既存録画の所有者は変更しません。以前 root で録画したファイルや `/recorded/tmp` がある場合は、対象の権限を管理者が確認してください。無効時の EPGStation 実行ユーザーは従来どおりです。

1. `http://<録画ホストIP>:32769/` を開きます。初回起動で `EPGStation` プロファイルが自動作成されます。既に同名プロファイルがある場合は上書きしません。
2. WebUI で各放送局のロゴデータを登録し、サービス設定で対象局とロゴを対応付けます。対象局の「CM 解析無効」を解除し、JoinLogoScp コマンド (通常 `JL_標準.txt`) を確認します。プロファイルだけでは局別設定を代行できません。ロゴ未登録のジョブは待機・失敗するため、最初は短い実録画で確認してください。
3. EPGStation の録画画面からエンコードを実行し、設定一覧の **Amatsukaze** を選びます。接続先やエンコードコマンドの手編集は不要です。
4. 自動化する場合は EPGStation の自動予約ルールを開き、録画後エンコード設定に **Amatsukaze** を選んで保存します。まず TS の自動削除は無効のまま、CM 境界・ロゴ消し・音声・完了結果の再生を確認します。

`EPGStation` プロファイルは上流 `defaults/profile/デフォルト.profile` の XML を基に、名前を `EPGStation`、`DisableChapter=false`、`OutputMask=2` (CM カット) に変更したものです。`EncoderType=x264`、MP4、`NoDelogo=false` (ロゴ消し有効)、CUDA 無効、入力移動・リネーム無効です。字幕は上流既定どおり無効です。局別ロゴと CM 解析設定は必要です。WebUI で品質やインターレース解除、字幕を調整してください。

GPU 利用時も初期プロファイルは x264 のままです。Intel/AMD は `compose.intel.yaml` に加えて `compose.amatsukaze.intel.yaml`、NVIDIA は `compose.nvidia.yaml` に加えて `compose.amatsukaze.nvidia.yaml` を選びます。setup.sh は Amatsukaze 有効時だけ専用ファイルを追加します。GPU ファイルだけで未定義サービスが作られることを避けるため、共通 GPU override に Amatsukaze のサービス定義は混ぜていません。WebUI で `EPGStation` を複製し、QSVEnc/NVEnc/VCEEnc を選択して実機確認するか、`EPGStation` のエンコーダーを変更してください。プロファイル名は EPGStation 側のコマンド引数と一致させます。

### 自動生成する EPGStation 設定

MariaDB 用テンプレートを entrypoint で展開し、有効時だけ次を挿入します。既存の H.264 プリセットも残ります。

```yaml
amatsukaze:
    host: amatsukaze
    port: 32768
    addTaskPath: /opt/amatsukaze/AmatsukazeAddTask
    profile: EPGStation
    priority: 3
    noMove: true
    connectTimeoutMs: 60000
    taskTimeoutMs: 0
    pathMappings: []

encode:
    - id: amatsukaze
      name: Amatsukaze
      cmd: '%NODE% %ROOT%/dist/AmatsukazeEncodeTool.js EPGStation'
      suffix: .mp4
      rate: 12.0
    - id: h264-720p
      name: H.264
      cmd: '%NODE% %ROOT%/config/enc.js h264 720'
      suffix: .mp4
      rate: 10.0
      video:
          codec: libx264
          height: 720
      audio:
          codec: aac
```

`rate: 12.0` はキュー待ちを含めた番組長の 12 倍のタイムアウトです。大量のキューでは待機時間を考慮してください。`taskTimeoutMs: 0` は Amatsukaze の無変化監視タイムアウトを無効にする値です。

### 永続化とパス

| ホスト | EPGStation | Amatsukaze | 用途 |
| --- | --- | --- | --- |
| `${RECORDED_DIR}` | `/recorded` | `/recorded` | 録画 TS と EPGStation が指定するエンコード出力先 |
| `config/amatsukaze/{avs,bat,config,drcs,JL,logo,profile}` | 対象外 | `/app/` 以下の同名ディレクトリ | スクリプト、設定、外字、CM 解析、ロゴ、プロファイル |
| `data/amatsukaze/{data,input,output}` | 対象外 | `/app/` 以下の同名ディレクトリ | キュー・ログ・手動入出力 |

初回起動時にイメージ内の既定ファイルを空の永続化先へコピーします。以降は存在するファイルを上書きしません。`/app/input` / `/app/output` は Amatsukaze 単独で使う場合の場所で、EPGStation 連携では両コンテナの `/recorded` を使います。上流 entrypoint の `/app` 所有者変更が録画全体へ及ばないよう、録画先は `/app/input` に重ねてマウントしていません。

EPGStation フォークは `INPUT` を `-f`、`dirname(OUTPUT)` を `-o` に渡します。Amatsukaze が決めた実際の出力ファイルをその場所で登録し、予定された `OUTPUT` 名への移動は行いません。同名出力の上書きに注意し、同じ TS の再エンコードは別フォルダーを指定してください。EPGStation の画面で出力先を追加する場合も共有 `/recorded` 以下に置きます。`pathMappings` は空でよく、別構成に変更する場合は `local` (EPGStation) → `remote` (Amatsukaze)、完了時は逆方向に変換されます。

### バージョン・アーキテクチャ・接続

`docker/amatsukaze/Dockerfile` は [上流タグ 1.1.1.2 の Dockerfile](https://github.com/rigaya/Amatsukaze/blob/1.1.1.2/docker/Dockerfile) を基にしています。上流は `releases/latest` を参照するため、その取得部分を `AMATSUKAZE_VERSION` の固定 URL に変更しました。既定は `1.1.1.2`。依存ライブラリー、エンコーダー、fdkaac のビルド、Docker 設定補正を維持しています。OS パッケージまでの完全な再現ビルドを保証するものではありません。

EPGStation イメージも同じバージョンの単体 `AmatsukazeAddTask_linux_<ver>_<x64|arm64>.tar.xz` を有効時だけ取得します。[上流リリースワークフロー](https://github.com/rigaya/Amatsukaze/blob/1.1.1.2/.github/workflows/build_amatsukazeaddtask.yml) は .NET の `--self-contained true` / `PublishSingleFile=true` を使います。別途 dotnet/Mono は不要です。ネイティブ依存の ICU / OpenSSL / zlib / libstdc++ をイメージに入れています。サーバーの 1.1.1.2 配布物と同梱ツールは x64 のみなので、このサービスは `platform: linux/amd64` 固定です。ARM64 ホストでのサーバー実行はエミュレーション前提で未検証です。GPU 使用は対応する x86_64 Linux ホストで確認してください。

TCP 32768 は Compose 内だけで使用し、ホストへ公開しません。Windows の AmatsukazeClient を使う場合だけ、ローカル override に次を加え、そのファイルを `COMPOSE_FILE` の末尾へ追加します。

```yaml
services:
  amatsukaze:
    ports:
      - "32768:32768"
```

WebUI は `AMATSUKAZE_WEBUI_PORT` (既定 32769) で公開します。今回の HTTPS gateway には追加していません。任意サービスの依存関係を既存 gateway へ持ち込まず、Amatsukaze の経路を標準では追加しないためです。必要なら専用 gateway override で HTTP 転送を追加してください。WebUI / TCP は信頼できる LAN/VPN 内に限定し、公開ポートのファイアウォール設定にも 32769 (必要時 32768) を加えます。

### Amatsukaze のトラブルシュート

| 症状 | 確認と対処 |
| --- | --- |
| キュー投入失敗 / 接続拒否 | `docker compose logs amatsukaze epgstation` と EPGStation エンコード詳細を確認。内部接続は `amatsukaze:32768`。初回サーバー起動完了を待つ |
| プロファイルがない | WebUI で `EPGStation` の存在を確認。`config/amatsukaze/profile/EPGStation.profile` の権限・XML と起動ログを確認。編集済みファイルは再起動で上書きされない |
| パスが見つからない | 両コンテナの `/recorded` に同じファイルがあるか確認。出力先も `/recorded` 以下にする。ホスト側パスや `/app/output` を EPGStation の出力先に指定しない |
| ロゴ待ち / CM カットされない | WebUI のサービス設定でロゴを割り当て、CM 解析無効を解除。`JL_標準.txt` と放送局固有設定を確認 |
| 保存に失敗 / permission denied | `.env` の `RUN_UID` / `RUN_GID` と録画・出力ディレクトリの権限を確認。既存 TS の所有権は自動変更しない |
| 再エンコードで以前の出力が置き換わる | Amatsukaze が入力名から出力名を決めるため、出力先フォルダーを分ける |
| GPU が使われない | 専用 GPU override、ホストのドライバーと Toolkit、WebUI のプロファイルのエンコーダー選択を確認。初期値は x264 |

根拠: [ProfileSetting と出力マスク](https://github.com/rigaya/Amatsukaze/blob/1.1.1.2/AmatsukazeServer/Server/EncodeServerData.cs)、[局別 CM 解析・ロゴ消しの適用](https://github.com/rigaya/Amatsukaze/blob/1.1.1.2/AmatsukazeServer/Server/TranscodeWorker.cs)、[上流既定プロファイル](https://github.com/rigaya/Amatsukaze/blob/1.1.1.2/defaults/profile/デフォルト.profile)、[Linux インストール](https://github.com/rigaya/Amatsukaze/blob/1.1.1.2/doc/InstallLinux.md)、[EPGStation 連携コマンド](https://github.com/stuayu/EPGStation/blob/main/src/AmatsukazeEncodeTool.ts)、[パス変換](https://github.com/stuayu/EPGStation/blob/main/src/model/amatsukaze/AmatsukazeConfigResolver.ts)。


## EPGStation の DB (MariaDB 固定)

`compose.yaml` に `mariadb:latest` を標準サービスとして定義しています。SQLite の選択肢・DB 用 override・profile はありません。`./setup.sh --reconfigure` でも空またはサンプル値のパスワードを 24 バイトの乱数 (48 桁の hex) に置き換え、`.env` に保存します。設定済みの値は維持します。`.env` は mode 600 で保存します。以前の `COMPOSE_FILE` にあった DB 用 override と `COMPOSE_PROFILES` の `mariadb` は setup.sh の再実行で除去します。

接続設定は `dbtype: mysql`、`host: mariadb`、`port: 3306`、`user/database: epgstation`、`charset: utf8mb4` です。setup.sh が `.env` の `MARIADB_PASSWORD` を YAML 文字列として安全に `config/epgstation/config.yml` へ埋め込み、MariaDB の `healthcheck.sh --connect --innodb_initialized` 成功後に EPGStation を起動します。サーバーも `utf8mb4` / `utf8mb4_general_ci` を明示します。根拠: EPGStation フォークの [IConfigFile.ts:297-304](https://github.com/stuayu/EPGStation/blob/main/src/model/IConfigFile.ts#L297-L304)、[ConfigSchema.ts:1060-1080](https://github.com/stuayu/EPGStation/blob/main/src/model/config/ConfigSchema.ts#L1060-L1080)、[DBOperator.ts:67-86](https://github.com/stuayu/EPGStation/blob/main/src/model/db/DBOperator.ts#L67-L86)、[ormconfig.js:34-42](https://github.com/stuayu/EPGStation/blob/main/ormconfig.js#L34-L42)、[MariaDB の作成例](https://github.com/stuayu/EPGStation/blob/main/doc/windows-setup.md#L292-L299)。MySQL 専用の `utf8mb4_0900_as_ci` は採用していません。

`MARIADB_AUTO_UPGRADE=1` は、起動時に必要性を判定して `mariadb-upgrade` を実行する公式イメージの機能です。システム DB のバックアップ `system_mysql_backup_*.sql.zst` も既定で作成されます。これは利用者 DB 全体のバックアップではないため、メジャー更新前は録画予約 DB を別途バックアップしてください。既存データ領域のパスワードは環境変数の変更だけでは更新されません。[公式環境変数仕様](https://mariadb.com/docs/server/server-management/automated-mariadb-deployment-and-administration/docker-and-mariadb/mariadb-server-docker-official-image-environment-variables)

以前 SQLite で動かしていた場合、既存の予約・履歴は自動移行されず、新しい MariaDB で開始します。SQLite ファイルは削除しません。

## EDCB と Material WebUI (任意、初回既定ではい)

`./setup.sh` が選択・ポート・実行 UID/GID・仮想チューナー数を設定します。非対話では `EDCB=yes ./setup.sh --yes`、無効にする場合は `EDCB=no ./setup.sh --yes` を指定します。選択は `SETUP_EDCB` に保存します。設定だけなら `--reconfigure` を付け、`make build && make up` で反映します。EDCB 無効時は EDCB 用サービス・HTTPS 経路を読み込みません。KonomiTV のバックエンドは引き続き recisdb-proxy の Mirakurun 互換 API です。

EDCB `my-build` を Debian bookworm で `make -C Document/Unix` / `install_u` によりビルドします。Lua は Debian の `liblua5.2-dev` / `lua-zlib` を利用します。Material WebUI は本家 [EMWUI/EDCB_Material_WebUI](https://github.com/EMWUI/EDCB_Material_WebUI) の `E3` ブランチから `HttpPublic` と `Setting` を組み込みます。WebUI は `/E3/` で配信されます (`http://<録画ホストIP>:5510/E3/`)。E3 の導入手順 (`HttpPublic` と `Setting` の配置、`HttpPort=5510`、`HttpNumThreads` の増設) と EDCB 側の要件 (Lua 5.2) を確認し、`configure.py` は `HttpNumThreads=50` を初期値にします。E3 が呼ぶ EDCB Lua API は `stuayu/EDCB` の `my-build` の `Document/Readme_Mod.txt` に記載されたものだけで、`FindFilePlain` は `FindFile` が無いときの代替です。根拠: [E3 導入](https://github.com/EMWUI/EDCB_Material_WebUI/blob/E3/README.md#導入)、[Readme_Mod.txt](https://github.com/stuayu/EDCB/blob/my-build/Document/Readme_Mod.txt)、[util.lua の FindFile 分岐](https://github.com/EMWUI/EDCB_Material_WebUI/blob/E3/HttpPublic/E3/util.lua)。ソースは Docker ビルド時に取得し、このリポジトリには複製しません。EpgTimerSrv はコンテナ内でフォアグラウンド常駐し、tini と `restart: unless-stopped` が管理します。systemd は不要です。停止猶予は上流の unit 例に合わせて 50 秒です。根拠: [HowToBuild.txt の Linux 節](https://github.com/stuayu/EDCB/blob/my-build/Document/HowToBuild.txt#L104-L200)、[Unix/Makefile](https://github.com/stuayu/EDCB/blob/my-build/Document/Unix/Makefile)、[WebUI の配置](https://github.com/EMWUI/EDCB_Material_WebUI/blob/E3/README.md#導入)。

### チューナー接続方式の比較

| 方式 | 確認結果 | 判断 |
| --- | --- | --- |
| (A) bondriver-proxy-client → TCP 40070 | Linux ターゲットの `cargo check` と `.so` クロスビルドは成功。ただし Rust の手製 vtable は Linux EDCB の C++ RTTI と非互換。`CreateBonStruct` は未実装 | 現時点では不採用。BNDP 固有の優先度・排他制御を直接扱える将来案 |
| (B) BonDriver_LinuxMirakc → HTTP 40080 | `/mirakurun/api/services` と `/mirakurun/api/services/:id/stream` が実装済み。サービスストリームは `X-Mirakurun-Priority` を録画クラス・競合優先度に反映 | 今回採用。ビルド時に下記の互換補正を適用 |

(A) の障害は `extern "system"` や UTF-16 という名前だけで判断したものではありません。EDCB は `dlopen` / `dlsym` でロードし、`CreateBonStruct` があれば C 構造体アダプターを使い、なければ `CreateBonDriver` の戻り値に `dynamic_cast<IBonDriver2*>` を使います。EDCB の文字列自体は Linux でも `BON16CHAR` (16 bit) であり、UTF-16 は問題ではありません。Rust 側は非 Windows でもコンパイル可能ですが、Linux 向け RTTI メタデータを持つ C++ オブジェクトではありません。根拠: EDCB [BonDriverUtil.cpp:178-202](https://github.com/stuayu/EDCB/blob/my-build/BonCtrl/BonDriverUtil.cpp#L178-L202)、[IBonDriver2.h:15-75](https://github.com/stuayu/EDCB/blob/my-build/BonCtrl/IBonDriver2.h#L15-L75)、[PathUtil.cpp:367-386](https://github.com/stuayu/EDCB/blob/my-build/Common/PathUtil.cpp#L367-L386)、recisdb [interface.rs:1-20](https://github.com/stuayu/recisdb-proxy-rs/blob/feature/proxy/bondriver-proxy-client/src/bondriver/interface.rs#L1-L20)。

recisdb-proxy-rs 側に必要な改修は、Linux 向け `CreateBonStruct` / `STRUCT_IBONDRIVER2` の実装です。`pCtx`、`pEnd`、C ABI の関数ポインターを EDCB の定義に合わせ、`GetTsStream` のコピー版→ポインター版の順序も確認する必要があります。DLL パス検出の代わりに `.so` 隣接 INI の検出も必要です (現行の非 Windows 設定パスはカレントディレクトリ基準)。もう一案は C++ RTTI を持つラッパーですが、C 構造体エクスポートのほうがコンパイラー依存を避けられます。このリポジトリでは (A) を実装せず、recisdb-proxy-rs は変更していません。

(B) の上流は `/api/` 固定・数値 IPv4 接続・`service.channel` がオブジェクトの想定です。この構成では `docker/edcb/patch-driver.py` がビルド中の外部ソースに対して `/mirakurun/api/`、URL バッファ拡張、`channel[0]`、DNS 解決、空間数 64、切断時の双方向 shutdown を補正します。想定とソースが変わればビルドを失敗させます。`SERVICE_SPLIT=1` を使う理由は、現行の channel-stream 経路は優先度ヘッダーを読まず視聴扱いになる一方、service-stream 経路はヘッダーを解釈するためです。サービス取得順とチューニング空間の切り替わり順を ChSet の変換でも再現します。

根拠: [上流 BonDriver 本体](https://github.com/matching/BonDriver_LinuxMirakc/blob/main/src/BonDriver_LinuxMirakc.cpp#L405-L555)、[HTTP 接続](https://github.com/matching/BonDriver_LinuxMirakc/blob/main/src/http_proc.hpp#L87-L110)、recisdb [サービス定義](https://github.com/stuayu/recisdb-proxy-rs/blob/feature/proxy/recisdb-proxy/src/web/mirakurun.rs#L444-L478)、[service stream](https://github.com/stuayu/recisdb-proxy-rs/blob/feature/proxy/recisdb-proxy/src/web/mirakurun.rs#L1093-L1160)、[channel stream](https://github.com/stuayu/recisdb-proxy-rs/blob/feature/proxy/recisdb-proxy/src/web/mirakurun.rs#L1213-L1315)。

### 自動生成する設定と保存先

| ファイル / 項目 | 初期値 |
| --- | --- |
| `Common.ini` | `DataSavePath=/var/local/edcb/Setting`、`RecFolderNum=1`、`RecFolderPath0=/recorded/edcb` |
| `EpgTimerSrv.ini [SET]` | `EnableHttpSrv=1`、`HttpPort=5510`、`HttpPublicFolder=/var/local/edcb/HttpPublic`、IPv4 loopback/RFC1918 LAN を許可、`EnableTCPSrv=0`、`RecEndMode=0` |
| `[BonDriver_LinuxMirakc.so]` | `Count=EDCB_TUNER_COUNT` (既定 2)、`Priority=1` (EDCB 内部 ID)、`GetEpg=1`、`EPGCount=1` |
| `[EPG_CAP]` | 毎日 06:00 / 18:00、両方有効 |
| `[TVTEST]` | `Num=1`、`0=BonDriver_LinuxMirakc.so` |
| `[REC_DEF]` | `RecMode=3` (指定サービスのみ・B25 処理なし) |
| `EpgDataCap_Bon.ini [SET]` | `Scramble=0`、`EMM=0` |
| `BonDriver_LinuxMirakc.so.ini [GLOBAL]` | `SERVER_HOST=recisdb-proxy`、`SERVER_PORT=40080`、`SERVER_TYPE=http`、`DECODE_B25=0`、`PRIORITY=2`、`SERVICE_SPLIT=1` |

編集する INI と ChSet は `config/edcb/` に置き、EDCB の既定パスからリンクします。EDCB の INI 保存は同じファイルを書き換えるため、リンク先が更新されます (`Common/PathUtil.cpp` の `WritePrivateProfileString`)。予約・録画履歴・自動予約・EPG・ログ・WebUI コードは `data/edcb/` に残します。旧設定は setup.sh がコピーし、起動時に旧パスを `.pre-config-migration` として残してからリンクします。録画は各録画先の `edcb/` に保存します。UID/GID を合わせて起動し、既存録画全体の所有者は変更しません。チューナー数や保存先を変更した場合は、録画がないときに EDCB を停止し、`make regen-config SERVICE=edcb` の差分を確認してから `make up` を実行してください。既存プリセット・予約に保存された個別設定は E3 でも確認してください。

recisdb-proxy がサーバー側で復号し、互換 API の `decode` クエリ値は解釈されません。EDCB 側に B25 ライブラリーは導入せず、上記のアプリ設定と既定予約モードで CAS 処理を無効にします。WebUI で別の録画プリセットを追加する場合も「B25 処理なし」を選びます。根拠: recisdb [mirakurun.rs:1093-1108](https://github.com/stuayu/recisdb-proxy-rs/blob/feature/proxy/recisdb-proxy/src/web/mirakurun.rs#L1093-L1108)、EDCB [CommonDef.h:22-25](https://github.com/stuayu/EDCB/blob/my-build/Common/CommonDef.h#L22-L25)、[TunerBankCtrl.cpp:793-802](https://github.com/stuayu/EDCB/blob/my-build/EpgTimerSrv/EpgTimerSrv/TunerBankCtrl.cpp#L793-L802)、[AppSetting.cpp:37-40](https://github.com/stuayu/EDCB/blob/my-build/EpgDataCap_Bon/EpgDataCap_Bon/AppSetting.cpp#L37-L40)。

その他の設定キーの根拠: EDCB [PathUtil.cpp:401-409,479以降](https://github.com/stuayu/EDCB/blob/my-build/Common/PathUtil.cpp#L401-L409)、[ReserveManager.cpp:24-47](https://github.com/stuayu/EDCB/blob/my-build/EpgTimerSrv/EpgTimerSrv/ReserveManager.cpp#L24-L47)、[EPG 時刻設定](https://github.com/stuayu/EDCB/blob/my-build/EpgTimerSrv/EpgTimerSrv/EpgTimerSrvSetting.cpp#L70-L105)、[HTTP 設定](https://github.com/stuayu/EDCB/blob/my-build/Document/Readme_Mod.txt#L848-L869)、[録画プリセット](https://github.com/stuayu/EDCB/blob/my-build/EpgTimerSrv/EpgTimerSrv/EpgTimerSrvMain.cpp#L3247-L3268)。

### ChSet の自動投入・再取得

1. 起動時に recisdb-proxy の永続 DB を読み取り専用で開き、`web_auth_config.auth_token` を取得します。利用者による token の転記は不要です。
2. 認証付き `/api/client-view/targets` で登録済みドライバーを列挙し、`/api/client-view/files/chset4?tuner=...` と `chset5?tuner=...` を取得します。
3. `/mirakurun/api/services` の順番に合わせて空間・チャンネル番号を変換し、サービスを統合します。`BonDriver_LinuxMirakc(LinuxMirakc).ChSet4.txt` と `ChSet5.txt` を `config/edcb/Setting` に UTF-8 BOM で保存します。BNDP 用の ChSet4 をそのまま置くことはできません。
4. 未スキャン・認証失敗・不正応答なら既存ファイルを保持し、ログへ理由を出します。初回は ChSet なしでも WebUI を起動します。recisdb-proxy でスキャンを完了してから `make edcb-chset` を実行してください。

`make edcb-chset` は EDCB を停止し、一時コンテナで再取得・番号変換・既存ファイルの日時付きバックアップを行い、EDCB を再起動します。録画中は実行しないでください。取得失敗時も既存 ChSet を残して EDCB を再起動します。チャンネル追加・削除やスキャン後にも必要です。仮想番号が変わるため、再取得後は既存予約のチャンネルを確認してください。初回の EPG は次の定期取得、または WebUI の EPG 取得操作で読み込みます。recisdb の EPG DB を EDCB に直接コピーする処理ではありません。

根拠: recisdb [client_view.rs:34-123,244-290](https://github.com/stuayu/recisdb-proxy-rs/blob/feature/proxy/recisdb-proxy/src/web/api/client_view.rs#L244-L290)、[ChSet の列形式](https://github.com/stuayu/recisdb-proxy-rs/blob/feature/proxy/recisdb-proxy/src/web/channel_files.rs#L196-L259)、[token の保存](https://github.com/stuayu/recisdb-proxy-rs/blob/feature/proxy/recisdb-proxy/src/database/mod.rs#L2017-L2037)、EDCB [ChSet のファイル名](https://github.com/stuayu/EDCB/blob/my-build/BonCtrl/ChSetUtil.cpp#L16-L34)、上流 BonDriver [GetTunerName](https://github.com/matching/BonDriver_LinuxMirakc/blob/main/src/BonDriver_LinuxMirakc.cpp#L301-L311)。

### ポート・併用・バージョン固定

`.env` の `EDCB_WEB_PORT` (既定 5510) を内部 5510 へ、HTTPS 併用時は `EDCB_HTTPS_PORT` (既定 8553) を Akebi の内部 8553 へ公開します。EDCB の TCP 制御ポートは公開しません。EDCB の HTTP ACL は RFC1918 LAN を許可します。公開 IPv4 / IPv6 の直接アクセスは初期 ACL では対象外です。各 WebUI と同様、信頼できる LAN/VPN 内で使用してください。

KonomiTV と EPGStation の接続先は変えません。全サービスのストリームは recisdb-proxy のチューナープールで調停されます。ただし各録画アプリの予約スケジューラーは独立しており、合計の同時録画・視聴が物理チューナー数を超えると確保失敗や視聴停止が起きます。LinuxMirakc の `PRIORITY=2` は EPG 取得にも適用され、BNDP のように操作ごとの優先度・排他フラグを指定する構成ではありません。短い予約録画と KonomiTV 同時視聴で確認してください。Material WebUI の基本の番組表・予約管理を対象とし、トランスコード配信の追加ツール・局ロゴ登録は上流の手順が別途必要です。

ビルド引数は `.env` の `EDCB_REF=my-build`、`EDCB_WEBUI_REPO=https://github.com/EMWUI/EDCB_Material_WebUI.git`、`EDCB_WEBUI_REF=E3`、`EDCB_BONDRIVER_REF=main` から渡します。コミット固定する場合は各値を完全なコミット SHA に置き換え、`docker compose build --no-cache edcb` を実行します。ブランチ追従時の更新にも `--no-cache` が必要です (Docker はブランチ先端の変更だけではソース取得レイヤーを無効にしません)。上流ソース変更時は互換補正の検査が失敗することがあり、`patch-driver.py` の見直しが必要です。


### この変更の検証範囲

Mac 上で shellcheck、bash 構文検査、`make test`、Compose YAML 読み込み、Compose v2.39.4 の実際の `config` による 24 通り (EDCB × Amatsukaze × HTTPS × GPU 3 種) の構成検証を実施しました。`tests/compose_test.py` は `COMPOSE_BIN=/path/to/docker-compose python3 tests/compose_test.py` で再実行できます。

設定ファイルの初回生成・再生成・移行・バックアップと復元は `tests/config_test.py` と `tests/setup_test.sh` で、Docker をスタブに置き換えて検証しています。実際のコンテナ起動による確認は含みません。

生成した EPGStation config.yml はローカルフォークの実物の `IConfigFile.ts` に対して TypeScript の `Partial<IConfigFile>` で型照合し、`ConfigSchema.ts` の DB キーも確認しました。EDCB、Lua 5.2、両候補の BonDriver は x86_64 Linux ELF にクロスビルドしました。クロス環境では CC/CXX/LD/OBJCOPY を Linux 向けに指定し、古い sysroot 用に `-ldl -lrt` を明示しました。Dockerfile は bookworm の glibc と Debian 配布 Lua を使うため、このクロス環境向け補助指定は不要です。

この Mac には Docker daemon がないため、bookworm イメージ全体のビルド・起動、MariaDB 実接続、EDCB WebUI の実応答、EPG 取得、実録画・復号・KonomiTV との同時利用、Akebi 経路は未検証です。Linux 録画ホストでこれらを確認してください。


## 画面で選ぶセットアップと再設定

`./setup.sh` は次の順に進みます。チェックリストは Space で選択し、キャンセルすると設定前に中止できます。

1. ようこそ画面で処理内容と所要時間を確認します。
2. Docker / Compose、チューナー、px4_drv、GPU、カードリーダー、ファイアウォールの検出結果を確認します。不足しているソフトには導入を提案します。
3. EDCB・Amatsukaze・HTTPS の入口を選択します。初回はすべて有効です。
4. 録画先を複数選び、既定の保存先を選びます。
5. このマシンで BonCasRelay を動かすか、別マシンに接続するかを選びます。
6. 自動検出結果を初期値として GPU を確認します。
7. 必要な場合だけ詳細ポート設定を開き、EDCB 自動登録・エンコードと UID/GID を確認します。
8. 全設定の確認画面でセットアップを承認します。
9. ビルド・起動中は進捗画面を表示します。ログは `data/setup-logs/<日時>-build.log` / `-start.log` に保存し、失敗時にも場所を表示します。
10. 完了画面で各 URL とチャンネルスキャン・録画確認の案内を確認します。EDCB は `http://<IP>:5510/E3/` です。

`./setup.sh --reconfigure` で現在の設定を初期値にして再選択できます。端末でない場合、`--yes`、画面ツールの導入を拒否した場合は従来の文字入力または既定値を使います。`--yes` は sudo 操作を承認しません。導入を含めて確認を省略する場合だけ `--auto-install` を明示します。このフラグは chown やサービス停止の確認も省略するため、表示される導入手順を事前に確認してください。

### 録画先をあとから変更する

`make storage` は録画先だけを選び直します。Docker の導入・ビルド・起動は行いません。`findmnt --json`、取得できなければ `lsblk --json`、さらに `df -PTk` からマウント済みファイルシステムを列挙します。空き容量・種別を表示し、NFS/CIFS も候補に含めます。`/`、`/boot`、`/snap`、tmpfs、overlay、Docker のデータ領域などは候補から外します。現在の保存先は候補に残します。

「その他のフォルダーを選ぶ…」では dialog のディレクトリ選択、whiptail では入力欄を使います。存在しないフォルダーは確認後に作成し、所有者・書き込み可否・空き容量を確認します。100 GB 未満では警告します。権限不足の場合は対象フォルダーだけの `sudo chown UID:GID <パス>` を表示して確認します。既存録画全体への再帰 chown はしません。

先頭は `.env` の `RECORDED_DIR`、全リストは `RECORDED_DIRS_JSON` に保存します。コンテナ内では `/recorded`、`/recorded2`、… とし、EPGStation の `recorded:`、KonomiTV の `video.recorded_folders`、EDCB の `RecFolderNum` / `RecFolderPathN` に反映します。EDCB はそれぞれの `edcb/` サブフォルダーを使います。Amatsukaze にも同じ `/recordedN` を渡すため、AddTask の入力・出力パスを共有できます。KonomiTV はホストパスとして `/recordedN` を設定し、実マウントは `/host-rootfs/recordedN` です。

既存の設定ファイルは初回生成の方針を守り、自動では書き換えません。選択変更後は次の差分を確認してください。安全な部分更新は任意の手編集と区別しにくいため、バックアップ付き再生成を採用しています。

```sh
make regen-config SERVICE=epgstation
make regen-config SERVICE=konomitv
make regen-config SERVICE=edcb       # EDCB 有効時、録画のない時間に停止して実行します
make up                            # マウント変更にはコンテナの再作成が必要です
```

保存先の削除・順序変更は既存 DB の録画パスにも影響します。古いマウントを外す前に、既存ファイルと DB の移行を確認してください。再生成はファイルの移動や DB の書き換えを行いません。非対話で複数選択する場合は、`RECORDED_DIRS_JSON='["/mnt/tv", "/mnt/tv2"]' ./setup.sh --yes` と指定できます。

### 不足ソフトの判定と導入の根拠

導入は Debian / Ubuntu のみ対応し、ほかのディストリビューションでは手順を表示します。導入済みは表示して飛ばします。実行する sudo コマンドと、導入用の `scripts/install-host.sh` 全体を表示して確認します。既存サービスへの影響がある NVIDIA runtime 設定後の Docker 再起動も確認対象です。

| 対象 | 判定・方法 | 根拠 |
| --- | --- | --- |
| Docker / Compose | `docker` と `docker compose version`。不足時は公式署名鍵・apt リポジトリを登録し `docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin` を導入します。グループ権限不足時は追加を提案し、再ログインを案内します | [Ubuntu 公式手順](https://docs.docker.com/engine/install/ubuntu/)・[Debian 公式手順](https://docs.docker.com/engine/install/debian/) |
| px4_drv | `lsusb` の VID `0511` と対応 PID、デバイスノード、`modinfo px4_drv` を確認します。未導入時は README 記載の `v0.6.1` DKMS Debian パッケージと kernel headers を導入し、modprobe・udev 設定を実行します。ファームウェアはパッケージが導入します | [px4_drv README](https://github.com/stuayu/px4_drv#インストール-linux)・[USB ID 定義](https://github.com/stuayu/px4_drv/blob/master/driver/px4_usb.h)・`driver/px4_usb.c` の対応表 |
| NVIDIA | `lspci` に NVIDIA があり `nvidia-ctk` がなければ、公式 apt リポジトリから Toolkit を提案します。GPU ドライバー自体は管理者が事前に導入します | [NVIDIA 公式手順](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) |
| Intel / AMD | `/dev/dri/renderD*` と render/video グループを確認します | 既存 GPU 構成と同じです |
| ファイアウォール | 読み取り可能な `ufw status` が有効なら、公開ポートの迂回を警告します。`ufw status` を読めない場合は `/etc/ufw/ufw.conf` の `ENABLED=yes` も確認し、実行時状態の確認を案内します。両方不明なら状態不明と表示します。設定は README のルーター ACL / DOCKER-USER 例に従います | [Docker のファイアウォール説明](https://docs.docker.com/engine/network/packet-filtering-firewalls/) |

USB PID は `083f,084a,023f,024a,073f,074a,084e,024e,0252,0253,004b,084b,0254,924e,0854,0855,0052` を照合します。カードリーダーは USB CCID インターフェースクラス `0x0b` (`lsusb -v` の decimal 11)、または制限時間付き `pcsc_scan -r` のリーダー列挙で検出します。USB 情報を読めない場合も手動で同梱を選べます。`--install-docker` は従来互換の別名として受け付け、共通の導入提案へ統合しています。

## BonCasRelay を同じマシンで動かす

local を選ぶと `compose.boncasrelay.yaml` を追加し、公開ソースから `cargo build --locked --release --no-default-features -p boncasrelay` でビルドします。`BONCASRELAY_REPO` / `BONCASRELAY_REF` で取得元を指定できます。PC/SC はコンテナ内の `pcscd`・`libpcsclite1`・`libccid` を使います。[BonCasRelay README と INI 例](https://github.com/stuayu/BonCasRelay#設定)に従い、`[General] ServerPort=6900` / `Allow`、`[Web] Listen` / `Enabled` を生成します。

カード通信はホストへ公開せず、recisdb-proxy の B25/4K 接続先はどちらも `boncasrelay:6900` です。WebUI はコンテナ内 `0.0.0.0:6980`、ホストでは `127.0.0.1:6980:6980` のみ公開します。UFW の 6900 許可ルールは同梱構成では不要です。別マシンの Relay を使う場合は、カードホスト側で録画ホスト IP からの 6900 を許可します。

`Allow=@compose-subnets@` を起動時にコンテナの接続済み IPv4 サブネットへ展開し、`/run/boncasrelay.ini` を生成します。Compose default network の IPAM は変更しません。複数サブネットには上流の INI 仕様に従って `Allow` を複数行出力します。以前の既定値 `Allow=172.30.69.0/24` も起動時に展開し、独自に指定した ACL は維持します。recisdb-proxy の既存 TOML を local に切り替える場合は `make regen-config SERVICE=recisdb-proxy` も必要です。

USB は `/dev/bus/usb` 全体をバインドし、`device_cgroup_rules: ['c 189:* rw']` で USB device major 189 の全 minor に読み書きを許可します。固定の `devices:` では再接続後のノード番号変更に対応できないため、この方式を採用しています。`privileged`・ホストの PC/SC socket・ホストネットワークは使いません。ただしコンテナから全 USB デバイスにアクセスできる点は把握してください。根拠は [Linux device 番号表](https://docs.kernel.org/admin-guide/devices.html)と [Compose device_cgroup_rules](https://docs.docker.com/reference/compose-file/services/#device_cgroup_rules) です。

さらに sysfs の CCID インターフェース (`bInterfaceClass=0x0b`) に対応する busnum/devnum の集合を 2 秒ごとに確認し、リーダーの増減・再列挙があればコンテナを終了して `restart: unless-stopped` で pcscd と Relay を起動し直します。[pcsc-lite の udev 実装](https://github.com/LudovicRousseau/PCSC/blob/1.9.9/src/hotplug_libudev.c)はイベントを監視しますが、コンテナ内へのホストイベント通知を前提にせず、再起動時の列挙で回復させます。無関係な USB 機器やチューナーの接続変更では再起動しません。`/dev/bus/usb` がなければ警告して監視を無効化し、サービスを起動します。`pcscd --hotplug` は非 USB リーダー用、`--force-reader-polling` は IFD の通知能力を無視する指定で、udev の USB 再検出ポーリングを有効にするものではありません ([Debian bookworm の manpage](https://manpages.debian.org/bookworm/pcscd/pcscd.8.en.html))。配布版 pcscd の udev 実装を継続利用し、CCID が変化した場合にだけ再起動して回復します。USB 抜き差し後の実際の再接続・復号は Linux 実機で確認してください。

ホストの `pcscd.service` または `pcscd.socket` が有効な場合は、両方の停止・無効化を表示して確認します。別アプリでもカードリーダーを使っている場合は、影響を確認してから選択してください。設定は `config/boncasrelay/boncasrelay.ini`、ログは `docker compose logs boncasrelay` です。

## EDCB の録画を EPGStation に自動登録する

EDCB 有効時に自動登録を質問します。既定は有効、登録後の Amatsukaze エンコードは既定で無効です。非対話では `EDCB_EPGSTATION=yes|no`、`EDCB_ENCODE=yes|no` で選べます。無効時は録画後フックを生成せず、Rust ツールもビルドしません。切り替え後は EDCB の再ビルドと、必要な設定の差分確認を行ってください。

[EDCB-to-EPGStation](https://github.com/stuayu/EDCB-to-EPGStation) の Rust 版を採用しています。`src/lib.rs` は標準の `PathBuf`・環境変数・sysinfo・reqwest を使い、Windows 専用 API を要求しません。ソースを別の一時ディレクトリにコピーし、Linux x86_64 向け release ビルドで ELF の生成を確認しました。Dockerfile は Linux ネイティブでビルドします。取得元は `EDCB_TO_EPGSTATION_REPO` / `EDCB_TO_EPGSTATION_REF` で指定できます。Python 版へのフォールバックは不要でした。

EDCB の [Unix バッチ仕様](https://github.com/stuayu/EDCB/blob/my-build/Document/Readme_Mod.txt)は実行権限付き `.sh` と環境変数渡しに対応します。ただし日時は ISO8601 の `StartTime` / `DurationSecond`、ファイル名は `FilePath` / `FileName` / `Title` です。`post-record.sh` と `post-record.py` で Rust 版が要求する `FILEPATH` / `FILENAME` / `TITLE` と分割日時へ変換し、日付をまたぐ録画も JST で扱います。上流ソースは変更しません。

初回に `config/edcb/EpgTimerSrv.ini` の `[REC_DEF] BatFilePath=/opt/edcb-stack/post-record.sh` を設定します。既存 INI は維持するため、既存環境では `make regen-config SERVICE=edcb` で差分確認するか E3 の既定プリセットを編集してください。すでに個別の録画後実行を持つプリセット・予約は自動では変更しません。自動登録を無効に戻す場合も、既存の録画後実行設定を外したことを確認してください。

接続先は `http://epgstation:8888/`、既定は `uploadMode: path`、元ファイル削除・プロセス待機・CPU 待機は無効です。EPGStation の `recorded:` と、localFilePath の許可リスト `importDirs:` に `edcb` → `/recorded/edcb`、追加保存先には `edcb2` → `/recorded2/edcb` などを生成します。追加保存先からの録画後実行では既定の登録先 `edcb` を対応する `edcbN` に置き換えた実行用設定を `data/edcb/upload/recordedN/` に作ります。利用者が指定した別の登録先は維持します。エンコード有効時は `mode: Amatsukaze` / `isSaveSameDirectory: true` / `removeOriginal: false` です。

**`path` はファイルを転送しませんが、現在の EPGStation API は元ファイルを録画管理フォルダーへ移動します。** 許可リストの根拠は `src/model/api/recorded/RecordedApiModel.ts` と `src/model/recorded/import/ImportPathValidator.ts`、移動の根拠は `src/model/operator/recorded/RecordedManageModel.ts` の `addUploadedVideoFile()` です。同じフォルダーでも衝突回避で名前が変わる場合があります。EDCB 側の録画履歴の元パスは追随しません。視聴・削除は登録後の EPGStation 側で管理してください。移動せず登録する別の external import API とは動作が異なります。

ツールは実行ファイルの隣の config/log を使うため、実行ファイルを `data/edcb/upload/` に配置し、config.yml はホスト設定へのリンクにしています。ログは `data/edcb/upload/edcb_to_epgstation.log` と `docker compose logs edcb` です。追加保存先は `data/edcb/upload/recordedN/edcb_to_epgstation.log` に出力します。ツール内で 5 MiB 超のログを 3 世代ローテーションします。

### 未登録録画の手動登録 (backfill)

UTF-8 JSON Lines の manifest を `data/edcb/backfill.jsonl` に用意します。時刻は Unix epoch のミリ秒、ONID/SID は十進文字列です。最初に dry-run を確認してください。

```json
{"filepath":"/recorded/edcb/example.ts","filename":"example","title":"番組名","onid":"4","sid":"101","startAt":1790000000000,"endAt":1790001800000,"recordedId":null}
```

```sh
docker compose exec --user 1000:1000 edcb /opt/edcb-stack/post-record.sh backfill /var/local/edcb/backfill.jsonl
docker compose exec --user 1000:1000 edcb /opt/edcb-stack/post-record.sh backfill /var/local/edcb/backfill.jsonl --apply --interval-sec 5 --limit 10
```

`1000:1000` は `.env` の RUN_UID/RUN_GID に合わせてください。状態は manifest 隣の `.state.jsonl` に記録します。backfill は常に path 登録で、エンコード・元ファイル削除は行いません。追加保存先は manifest を保存先ごとに分け、対応する `data/edcb/upload/recordedN/` の設定とバイナリーを確認してからそのバイナリーを直接実行してください。

登録されない場合は、録画後実行の指定、実行権限、EDCB の環境変数、`http://epgstation:8888/` への接続、EPGStation の `recorded:` の名前、両コンテナでのパスと UID/GID を確認します。既存 INI にフックがない場合や既存 EPGStation 設定に `edcb` がない場合は再生成が必要です。リトライ全失敗時は非 0 で終了し、録画ファイルをツールから削除しません。API がすでに移動したファイルや作成済み recorded エントリがないか確認し、手動再実行による二重登録を避けてください。

### 編集用設定の移行・再生成・バックアップ

EDCB は `data/edcb/*.ini` と `Setting` の INI/ChSet、Amatsukaze は `data/amatsukaze/{avs,bat,config,drcs,JL,logo,profile}` の不足ファイルを `config/` へコピーします。旧ファイルを消さず、新しい側があれば上書きしません。Amatsukaze のリリース既定値は初回コンテナ起動時に不足分だけ配置します。予約・履歴・EPG・ログ・キュー・キャッシュ・手動入出力は `data/` のままです。

Amatsukaze のエンコードがないことを確認して停止してから、`make regen-config SERVICE=amatsukaze` を実行してください。この処理は現在ビルドされたイメージの `/opt/amatsukaze-defaults` を起動処理なしで取得し、変更対象・テキスト差分を表示します。承認後に既存設定を `config/amatsukaze/backup/<日時>/` に退避して、イメージの既定値へ戻します。リリースに同梱されない `AmatsukazeServer.xml` / `UIState.xml` / `AutoSelectProfile.xml` は退避後に削除し、次回起動時に本体が既定値を生成します。根拠は Amatsukaze の `Server/EncodeServer.cs` の LoadAppData / LoadUIState / LoadAutoSelectData です。独自ファイルは維持します。ロゴなど同名のバイナリーも対象になり得るため、表示対象を確認してください。EDCB の再生成は INI のみで、予約や取得済み ChSet を消しません。

`make backup` / `make restore` は新しい `config/` 全体と生成済み `compose.storage.yaml` も対象にします。複数保存先すべてと MariaDB の生ファイルは除外し、DB は SQL dump にします。実行中の予約・キューを含む完全な整合性が必要な場合は、録画のない時間帯に該当サービスを停止してから実行してください。


更新時の設定移行は `make update` からも `render-config.py first-run` を実行します。
EDCB はコンテナ起動時にも同じ移行処理を使い、data 側に通常ファイルがあればその内容を優先します。
config 側に異なる内容があれば `.pre-config-migration` (重複時は日時付き) に退避し、移行をログへ表示します。
Amatsukaze は旧 data ディレクトリを読み取り専用で参照し、config 側にない設定・素材だけを既定値より先にコピーします。

EDCB 自動登録を有効にしたときは `make build` または `docker compose build edcb` で再ビルドしてください。
バイナリ未同梱なら警告し、自動登録を無効化して EDCB 本体は起動を続けます。
`EDCB_RECORDING_PATHS` は保存せず、録画先は `RECORDED_DIR` / `RECORDED_DIRS_JSON` から導出します。
ディスク別の uploader と設定は起動時に準備するため、設定変更後はコンテナを再起動してください。
無効時は `uploader-0` ステージを選択し、Rust を使う `uploader-1` には依存しません。
[BuildKit は依存しないステージをスキップします](https://docs.docker.com/build/building/multi-stage/#differences-between-legacy-builder-and-buildkit)。旧ビルダーは対象外です。
