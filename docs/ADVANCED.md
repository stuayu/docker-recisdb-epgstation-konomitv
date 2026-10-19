# 技術者向け設定・運用

## 必要なもの

- Linux 録画ホスト。Ubuntu 24.04 LTS または Debian 12 を推奨します。
- 全 Dockerfile の builder / runtime を Ubuntu 24.04 LTS (noble) に統一しています。KonomiTV の runtime は Ubuntu 24.04 ベースの CUDA イメージです。Intel Gen9〜11 の Media SDK / legacy1 OpenCL と新世代 oneVPL、AMD VA-API / AMF / ROCm に対応します。GPU 自動検出・実エンコード判定・手動設定保護と実機確認手順は [GPU 設定ガイド](GPU.md) を参照してください。
- Docker Engine と Compose v2。初回ビルドに数 GB の空きディスク容量が必要です。メモリは 8 GB 以上を推奨します。
- recisdb-proxy-rs が対応するチューナーと Linux ドライバー。例: PLEX PX-W3U4 / PX-Q3U4 / PX-MLT 系、DTV02A など。型番・ドライバー版で対応状況が異なります。`/dev/px4video*`、`/dev/pt3video*`、`/dev/pxmlt5video*`、`/dev/isdb2056video*` または `/dev/dvb/adapterN` のノードを使います。`isdb6014video*` は参照 README に対応記載がありません。
- B-CAS または ACAS カードとカードリーダー。カードホストと録画ホストは同じ LAN に置いてください。カードホストは録画ホストと同じマシンでも構いません。
- KonomiTV の Dockerfile を含むソース。セットアップが `stuayu/KonomiTV` を取得できます。


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

Intel / AMD はホストに `/dev/dri/renderD*` があることを確認します。setup.sh は選択 GPU の vendor ID に対応する render node を選び、`RENDER_GID` と AMD 用 `VIDEO_GID` を保存します。GPU override は recisdb-proxy・EPGStation・KonomiTV と、有効時の Amatsukaze にデバイスとグループを渡します。AMD の `/dev/kfd` は ROCm/OpenCL 用の任意デバイスで、存在する場合だけ追加 overlay で渡します。チューナーデバイスはノードごとの所有 GID を `TUNER_GIDS` に保存し、recisdb-proxy に渡します。`make tuners` は USB や DVB デバイスの追加後に GID と Compose を再生成します。KonomiTV Dockerfile には Intel Media Driver (`intel-media-va-driver-non-free` 等) が含まれるため、Intel QSV / VAAPI 用ユーザー空間パッケージをホストへ重ねて入れる必要はありません。AMD VCE は [KonomiTV README の AMDGPU-PRO driver 節](https://github.com/stuayu/KonomiTV#linux---vceencc)を確認してください。

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
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu24.04 nvidia-smi
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
| ダッシュボード (EDCB 有効時) | `http://<IP>:5510/` | `https://<IPをハイフン区切り>.local.konomi.tv:8553/` |
| recisdb-proxy | `http://<録画ホストIP>:40080/` | `https://<IPをハイフン区切り>.local.konomi.tv:40443/` |
| EPGStation | `http://<録画ホストIP>:8888/` | `https://<IPをハイフン区切り>.local.konomi.tv:8443/` |
| EDCB WebUI / EMWUI (任意) | `http://<録画ホストIP>:5510/E3/` | `https://<IPをハイフン区切り>.local.konomi.tv:8553/E3/` |
| MariaDB | Compose 内 `mariadb:3306` のみ | 対象外 |
| Amatsukaze (任意) | `http://<録画ホストIP>:32769/` | 対象外 |
| KonomiTV | 対象外 | `https://<IPをハイフン区切り>.local.konomi.tv:7000/` |

ポート番号で転送先を切り替えます。KonomiTV は内蔵 Akebi を使い、HTTP 直通は対象外です。本体 Uvicorn がコンテナ内 `127.0.0.77` だけで待ち受け、HTTP 直通にはフォーク改造が必要です。

EDCB の `/` と `/index.html` はダッシュボード、`/E3/` は EMWUI、`/legacy/` は従来の WebUI です。HTTP サーバー標準トップは `/legacy/` メニューのリンクから `/server.html` で開けます。
表示名は `.env` の `DASHBOARD_TITLE` (既定 `録画サーバー`) で変更できます。サービス一覧・ポート・LAN IP は setup、`make update`、`make regen-config SERVICE=edcb` で `data/edcb/dashboard.json` に再生成します。この JSON は派生データなので直接編集せず、`.env` を変更してください。起動時に `HttpPublic/dashboard.json` からリンクし、再生成後はページの再読み込みで反映します。
HTTPS 経路を無効にした場合、ダッシュボードには HTTPS リンクを生成せず、HTTPS 専用の KonomiTV は一覧から除外します。KonomiTV 自体の内蔵 Akebi は引き続き起動します。同梱 BonCasRelay の Web ポートは `BONCASRELAY_WEB_PORT` (既定 6980) で変更でき、録画ホストのループバックにだけ公開します。

HTTPS gateway は `.env` の `COMPOSE_FILE` に `compose.https.yaml` が含まれる場合だけ起動します。setup.sh の既定は有効です。Akebi は SNI の `*.local.konomi.tv` に対する証明書を Keyless Server から取得し、TLS 終端後に内部 HTTP へ転送します。HTTP から HTTPS への自動リダイレクトはありません。

既定の `akebi.konomi.tv` は KonomiTV 開発者が運営する Keyless Server です。停止や運用方針変更の影響を受けます。自前の Keyless Server に切り替える場合は `.env` の `AKEBI_KEYLESS_SERVER_URL` を変更してください。構築方法は [Akebi README](https://github.com/tsukumijima/Akebi) を参照してください。

`*.local.konomi.tv` の名前解決は DNS Rebinding Protection に遮断される場合があります。ルーターの保護設定を調整するか、端末が公開 DNS を使うよう設定してください。LAN 限定アクセスを維持する場合は、DNS 設定とファイアウォールを合わせてください。


## 手動セットアップ (経験者向け)

```bash
./setup.sh --reconfigure
./scripts/gen-tuners.sh
```

`.env` の `BONCAS_B25_HOST`、`BONCAS_B25_PORT`、`BONCAS_4K_HOST`、`BONCAS_4K_PORT`、`RECORDED_DIR`、`TUNER_GIDS`、`TUNER_EXCLUDE`、`RENDER_GID`、`KONOMITV_SOURCE` を環境に合わせます。通常は `make tuners` と setup.sh が除外後のデバイス所有 GID を再計算します。旧 Intel 構成の `VIDEO_GID` は `RENDER_GID` の移行元として扱います。AMD の `VIDEO_GID` は video グループとして別に保存します。

```bash
docker compose config
docker compose build
docker compose up -d
make scan
docker compose logs -f recisdb-proxy
```

`.env` の `COMPOSE_FILE` は Compose ファイルのコロン区切りです。標準は `compose.yaml:compose.tuners.yaml`。Intel は `:compose.intel.yaml`、AMD は `:compose.amd.yaml` を加え、`/dev/kfd` があれば setup.sh が `:compose.amd.kfd.yaml` も加えます。NVIDIA は `:compose.nvidia.yaml`、EDCB は `:compose.edcb.yaml` を加えます。EDCB と HTTPS を併用するときは末尾に `:compose.edcb.https.yaml` も加えます。NVIDIA には NVIDIA Container Toolkit が必要です。MariaDB は標準で起動し、setup.sh がパスワードを自動生成します。

EPGStation の DB は MariaDB 固定です。設定ファイルは `setup.sh` が初回だけ `config/<サービス名>/` に生成します (テンプレートは `templates/` にあります)。既存のファイルは上書きしません。`BONCAS_B25_HOST` / `BONCAS_B25_PORT` は recisdb-proxy の設定へ、`BONCAS_4K_HOST` が空なら 4K 設定を省いて生成します。`.env` の値を後から変えた場合は、「設定ファイルの編集」の `make regen-config` を使ってください。


## 日々の操作

| 操作 | コマンド |
| --- | --- |
| 初回セットアップ | `make setup` |
| 状態と URL | `make status` |
| 起動 | `make up` |
| 停止 | `make down` |
| ログ | `make logs` または `docker compose logs -f recisdb-proxy` |
| チューナー再検出・Compose 再生成・proxy 再作成・登録 | `make tuners` |
| 除外デバイスの登録を確認付きで削除 | `make tuners-prune` (`YES=1` で確認省略) |
| 登録・再スキャン・EDCB 反映・局一覧更新 | `make scan` (録画・視聴がないとき) |
| EDCB チャンネル再取得 | `make edcb-chset` (EDCB の録画がないとき) |
| 再ビルド | `make build` |
| ソース更新・再ビルド・再起動 | `make update` |
| 録画先だけ変更 | `make storage` |
| 設定・テスト | `make config` / `make test` |
| 設定ファイルの再生成 | `make regen-config SERVICE=<名前>` |
| バックアップ・復元 | `make backup` / `make restore FILE=...` |

### 自動受信設定と再スキャン

`make tuners` はデバイスを再検出して Compose を再生成し、recisdb-proxy を必要に応じて再作成して登録します。続けて `make scan` で公開中デバイスを再スキャンし、EDCB と各サービスへ反映します。デバイスは 1 ノードまたは DVB frontend につき 1 登録、`max_instances=1`、`stream_format=ts`、グループ未指定です。`TUNER_EXCLUDE` は完全一致と glob に対応し、DVB adapter パスを指定すると frontend/demux/dvr 全体を除外します。除外済みデバイスの既存登録は自動削除せず警告します。削除する場合は BonDriver 画面か、一覧を確認して `make tuners-prune` を実行します。登録削除は既存局設定や予約に影響するため、通常のセットアップでは削除しません。

進捗は完了台数・待機中/スキャン中・経過秒を表示し、セットアップの TUI 使用時はゲージも表示します。上流の既定スキャン上限は 1 台 900 秒、確認間隔は 60 秒です。通常の受信環境での目安は 1 台数分ですが、実測値ではありません。8 台は順番に調べるため数十分を見込んでください。こちらの待機上限は 1 台ごとに `max(1200, サーバー上限 + 確認間隔×2 + 120)` 秒です。必要なら `python3 scripts/tuner-setup.py scan --timeout 2400` で変更できます。

`make scan` は録画・視聴がない時間帯に実行してください。EDCB を停止して INI と ChSet を反映し、EDCB・EPGStation・KonomiTV を再起動します。EDCB の `[BonDriver_LinuxMirakc.so] Count` と `.env` の `EDCB_TUNER_COUNT` は公開中の物理デバイス数へ同期し、変更前のファイルを日時付きで退避します。`[TVTEST] Num=1` はドライバーの種類数なので変更しません。地デジ 6 台・衛星 2 台でも仮想 Count は合計 8 台です。帯域別予約上限を表す設定ではないため、衛星の同時録画数には注意してください。

タイムアウト時も proxy 内のスキャンは継続します。キャンセル API はありません。0 局は「アンテナ・分配器・B-CAS ではなく電波の問題」と表示し、アンテナ接続を案内します。権限エラーはチャンネル列挙失敗として別表示します。失敗・0 局の場合は ChSet 更新とサービス再起動を行いませんが、上流が既に変更した局 DB は元に戻しません。詳細な根拠、API、上流改善事項、実機確認項目は [自動受信設定の調査・設計](TUNER_SETUP.md) を参照してください。


## よくある質問・トラブルシュート

| 症状 | 原因 | 対処 |
| --- | --- | --- |
| チャンネルが映らない | チャンネルスキャン未実施、受信状態、チューナー登録不備 | `make scan` で再試行。デバイス変更時は先に `make tuners`。ログとアンテナ受信を確認 |
| B25 復号できない | BonCasRelay 未起動、接続元許可漏れ、カード未認識 | `BONCAS_B25_HOST:PORT` へ TCP 接続できるか確認。Relay の `--allow` と Web 設定のリーダー判定を確認 |
| チューナーが見えない | デバイスノードなし、udev 権限、生成 Compose が古い | `ls -l /dev/px4video* /dev/dvb/adapter*/*`、`TUNER_GIDS`、`docker compose exec recisdb-proxy id`、`make tuners` を確認 |
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
| `compose.intel.yaml` / `compose.amd.yaml` / `compose.nvidia.yaml` | recisdb-proxy・EPGStation・KonomiTV への GPU 設定 |
| `compose.amd.kfd.yaml` | `/dev/kfd` がある AMD ホストでの ROCm/OpenCL 用設定 |
| `compose.boncasrelay.yaml` | 任意の BonCasRelay と USB カードリーダー、限定サブネット |
| `compose.storage.yaml` | 複数録画先の追加マウント。セットアップが生成します |
| `compose.edcb.yaml` | 任意の EDCB と Material WebUI |
| `compose.edcb.https.yaml` | EDCB と HTTPS の両方が有効な場合の Akebi 経路 |
| `compose.amatsukaze.yaml` | 任意の Amatsukaze と EPGStation 連携設定 |
| `compose.amatsukaze.intel.yaml` / `compose.amatsukaze.amd.yaml` / `compose.amatsukaze.nvidia.yaml` | Amatsukaze 有効時専用の GPU 設定 |
| `compose.amatsukaze.amd.kfd.yaml` | Amatsukaze と AMD KFD overlay の併用設定 |
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

recisdb-proxy の Web 認証は既定で無効です。`config/recisdb-proxy/recisdb-proxy.toml` の `[web] auth_enabled = false` を使います。アクセス元はファイアウォールで制限してください。認証を使う場合は `true` にし、`auth_token` を設定します。既存設定の `auth_enabled = true` は `first-run` で false に移行し、変更前を `config/recisdb-proxy/backup/` に退避します。`auth_token` 明示時は設定を維持します。token は DB の `web_auth_config.auth_token` に保存されます。Mirakurun API の `/mirakurun/api/*` は token 認証対象外で、Compose 内の EPGStation / KonomiTV は `http://recisdb-proxy:40080/mirakurun/` を使います。

EPGStation は `config/epgstation/config.yml` を `/app/config/config.yml` としてマウントします。起動時には書き換えず、ファイルがなければ起動を止めて setup.sh の実行を促します。ログ設定ファイルがなければフォークの `*.sample.yml` から生成し、`/app/logs` はホストの `data/epgstation-logs` に保存します。

KonomiTV フォークは Akebi をコンテナ内 `0.0.0.0:server.port` で待ち受け、同じコンテナ内の `127.0.0.77:(server.port + 10)` の Uvicorn へ転送します。`<IPをハイフン区切り>.local.konomi.tv` はクライアントから Akebi に送る Host 名です。外向けの入口は Compose が公開する `7000` 番ポートです。設定は `config/konomitv/config.yaml` を `/code/config.yaml` としてマウントします (初期値は `templates/konomitv/config.yaml.example`)。KonomiTV はこのファイルへ設定を保存するため、読み書き可能でマウントしています。実装根拠はフォークの `server/KonomiTV.py` と `server/app/routers/MaintenanceRouter.py` です。


## 設定ファイルの編集

設定ファイルは `setup.sh` が初回だけ生成します。ファイルが既にあれば上書きしないため、ホストで編集した内容は次の起動や再セットアップで消えません。編集後は表の操作でサービスを再起動してください。

| サービス | ホスト上で編集するファイル | コンテナ内のパス | 内容 | 編集後の操作 |
| --- | --- | --- | --- | --- |
| recisdb-proxy | `config/recisdb-proxy/recisdb-proxy.toml` | `/data/recisdb-proxy.toml` | BonCasLink 接続先、Web 認証、DB パス。初回セットアップでプレビュー用 FFmpeg / tsreadex を自動設定し、`data/recisdb/thirdparty/` に永続保存します | `docker compose restart recisdb-proxy` |
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


## EPGStation の DB (MariaDB 固定)

`compose.yaml` に `mariadb:latest` を標準サービスとして定義しています。SQLite の選択肢・DB 用 override・profile はありません。`./setup.sh --reconfigure` でも空またはサンプル値のパスワードを 24 バイトの乱数 (48 桁の hex) に置き換え、`.env` に保存します。設定済みの値は維持します。`.env` は mode 600 で保存します。以前の `COMPOSE_FILE` にあった DB 用 override と `COMPOSE_PROFILES` の `mariadb` は setup.sh の再実行で除去します。

接続設定は `dbtype: mysql`、`host: mariadb`、`port: 3306`、`user/database: epgstation`、`charset: utf8mb4` です。setup.sh が `.env` の `MARIADB_PASSWORD` を YAML 文字列として安全に `config/epgstation/config.yml` へ埋め込み、MariaDB の `healthcheck.sh --connect --innodb_initialized` 成功後に EPGStation を起動します。サーバーも `utf8mb4` / `utf8mb4_general_ci` を明示します。根拠: EPGStation フォークの [IConfigFile.ts:297-304](https://github.com/stuayu/EPGStation/blob/main/src/model/IConfigFile.ts#L297-L304)、[ConfigSchema.ts:1060-1080](https://github.com/stuayu/EPGStation/blob/main/src/model/config/ConfigSchema.ts#L1060-L1080)、[DBOperator.ts:67-86](https://github.com/stuayu/EPGStation/blob/main/src/model/db/DBOperator.ts#L67-L86)、[ormconfig.js:34-42](https://github.com/stuayu/EPGStation/blob/main/ormconfig.js#L34-L42)、[MariaDB の作成例](https://github.com/stuayu/EPGStation/blob/main/doc/windows-setup.md#L292-L299)。MySQL 専用の `utf8mb4_0900_as_ci` は採用していません。

`MARIADB_AUTO_UPGRADE=1` は、起動時に必要性を判定して `mariadb-upgrade` を実行する公式イメージの機能です。システム DB のバックアップ `system_mysql_backup_*.sql.zst` も既定で作成されます。これは利用者 DB 全体のバックアップではないため、メジャー更新前は録画予約 DB を別途バックアップしてください。既存データ領域のパスワードは環境変数の変更だけでは更新されません。[公式環境変数仕様](https://mariadb.com/docs/server/server-management/automated-mariadb-deployment-and-administration/docker-and-mariadb/mariadb-server-docker-official-image-environment-variables)

以前 SQLite で動かしていた場合、既存の予約・履歴は自動移行されず、新しい MariaDB で開始します。SQLite ファイルは削除しません。


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
10. 起動確認後に自動登録・スキャン・ChSet 反映・サービス更新を実行し、完了画面で各 URL と録画確認の案内を確認します。EDCB は `http://<IP>:5510/E3/` です。

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


## セットアップの追加オプションと初回確認

対話端末に whiptail または dialog があれば画面で選択できます。チューナー一覧は既定で全台選択し、前回の除外設定を反映します。`--yes` は `TUNER_EXCLUDE`（環境変数、次に `.env`）をそのまま使います。未接続チューナーは `.env` の `TUNER_EXCLUDE=/dev/dvb/adapter0,/dev/px4video0` のように除外できます。DVB は adapter 単位で除外でき、`/dev/dvb/adapter*` のような glob も使えます。除外デバイスは Compose に渡さず、登録・スキャン対象と GID 集計から外します。チューナーが未検出でも続行でき、ドライバー導入後に `make tuners && make scan` を実行できます。ビルドと起動を含めず設定だけ行う場合は `./setup.sh --reconfigure` を使います。

起動確認後、チューナー登録・チャンネルスキャン・EDCB ChSet 配置・局一覧更新を自動実行します。通常は Web 画面でのチューナー登録が不要です。受信できない場合は警告を表示してセットアップを続行し、`make scan` で再試行できます。`--no-scan` でこの処理を省略できます。2 回目以降は成功済みのスキャンと反映を省略し、新しいデバイスは登録・スキャンします。受信 0 局のデバイスは最後に表示します。アンテナ未接続なら `TUNER_EXCLUDE` に追加してください。

### 2. 番組表・録画・視聴を確認

1. recisdb-proxy のチューナー登録・スキャンはセットアップが自動実行します。Web 認証は既定で無効です。認証有効時は API token を `data/recisdb/recisdb-proxy.db` から読み取り専用で取得します。
2. 受信設定の警告が出た場合は、アンテナ・ドライバー・デバイス権限を確認して `make scan` を実行します。USB 追加・取り外し後は先に `make tuners` を実行します。
3. EPGStation は `http://<録画ホストIP>:8888/` または HTTPS 有効時の `https://<IPをハイフン区切り>.local.konomi.tv:8443/` を開き、番組表から予約します。EPGStation の Mirakurun 接続先は内部ネットワーク上の `http://recisdb-proxy:40080/mirakurun/` です。
4. KonomiTV (`https://<IPのドットをハイフンに変換>.local.konomi.tv:7000/`) を開いて初期設定し、チャンネル一覧からライブ視聴します。例: IP が `192.168.1.20` なら `https://192-168-1-20.local.konomi.tv:7000/`。KonomiTV は Akebi による HTTPS が必要で、IP のドットをハイフンにした `*.local.konomi.tv` が正規 URL です。DNS Rebinding Protection が有効なルーターでは名前解決を止められることがあります。その場合はルーターの保護設定を調整するか、公開 DNS を使います。初回起動には外部 DNS / Keyless サーバーとの通信も必要です。KonomiTV の URL 仕様と DNS 問題は [KonomiTV README](https://github.com/stuayu/KonomiTV#httpsaa-bb-cc-ddlocalkonomitv7000-の-url-について)を参照してください。KonomiTV の Mirakurun backend は予約録画に対応しないため、予約は EPGStation または EDCB を使います。
5. EDCB 有効時はスキャン成功後に ChSet と仮想チューナー数を自動反映します。`http://<録画ホストIP>:5510/E3/` を開きます。EDCB 自身によるチャンネルスキャンや接続設定の手編集は不要です。
6. 地デジ/BS のスクランブル放送で B25 復号、実際の予約録画と再生を確認します。4K は ACAS 対応構成と dantto4k が別途必要です。
