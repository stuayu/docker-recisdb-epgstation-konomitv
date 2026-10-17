# dtv-stack

Compose で recisdb-proxy、EPGStation、KonomiTV を連携。チューナーは recisdb-proxy のみに渡し、B-CAS / ACAS は別ホストの BonCasServer を BonCasLink で利用。

## 前提

- Linux ホストに対応チューナーと udev / device 設定を導入。
- BonCasServer の B-CAS / ACAS ポートを確認。一般的な初期値は 6900 / 6902。
- Docker Engine と Compose v2。
- KonomiTV のフォークを `../KonomiTV` に配置するか、`.env` の `KONOMITV_SOURCE` を指定。Compose はフォーク同梱の `Dockerfile` を直接使用。

## 初回起動

```sh
cp .env.example .env
# .env の BonCasServer アドレス、録画先、VIDEO_GID、KONOMITV_SOURCE を編集
make config
make tuners
docker compose build
docker compose up -d
docker compose logs -f recisdb-proxy
```

`make tuners` は実在する `/dev` ノードを検出し、gitignore対象 `compose.tuners.yaml` を生成。チューナー追加後は再実行。

初期設定:

1. recisdb-proxy ダッシュボード (`http://HOST:${RECISDB_WEB_PORT}`) でチューナー登録・チャンネルスキャン。
   `[web] auth_enabled = true` の初回トークンは `docker compose logs recisdb-proxy` の `Web API auth token:` 行。DBへ保存され、再起動時も同じ値をログへ出す。ダッシュボードへ入力。
2. `/mirakurun/api/*` は認証対象外。EPGStation/KonomiTV からトークンなしで使える。
3. EPG蓄積後、EPGStation (`http://HOST:${EPGSTATION_PORT}`) で番組表確認。内部接続先 `http://recisdb-proxy:40080/mirakurun/`。
4. KonomiTV (`http://HOST:${KONOMITV_PORT}`) 初期設定とライブ視聴を確認。Mirakurun backend は予約録画非対応。予約はEPGStation。
5. 実放送で予約録画・B25復号・KonomiTV再生を確認。

## チューナー・Compose設定

ベース `compose.yaml` はチューナーデバイスを列挙しない。`scripts/gen-tuners.sh` は recisdb-proxy の対応に基づき、`/dev/px4video*`、`/dev/pt3video*`、`/dev/pxmlt5video*`、`/dev/isdb2056video*` と `/dev/dvb/adapterN` 内 frontend/demux/dvr ノードを検出。参照ソースはpx4/pt3系文字デバイスとLinux DVBv5を扱う。`isdb6014video*` は参照ソースに記載がなく未対応扱い。`VIDEO_GID` はデバイスのグループIDに合わせる。recisdb-proxy は非root `app` ユーザーと追加グループで稼働。カードリーダーやpcscdは渡さない。

`.env` の `COMPOSE_FILE` はComposeファイルをコロン区切りで指定。標準は `compose.yaml:compose.tuners.yaml`。GPU設定を足す場合:

- Intel: `compose.yaml:compose.tuners.yaml:compose.intel.yaml`
- NVIDIA: `compose.yaml:compose.tuners.yaml:compose.nvidia.yaml`

## GPU起動

Intel QSV / VAAPI:

```sh
COMPOSE_FILE=compose.yaml:compose.tuners.yaml:compose.intel.yaml docker compose up -d --build
```

NVIDIA NVENC (NVIDIA Container Toolkit 必須):

```sh
COMPOSE_FILE=compose.yaml:compose.tuners.yaml:compose.nvidia.yaml docker compose up -d --build
```

## MariaDB

既定DBはSQLite。MariaDB使用時は `.env` に強い `MARIADB_PASSWORD` と `MARIADB_ROOT_PASSWORD` を設定し、`config/config.mariadb.yml.example` を確認。

```sh
COMPOSE_FILE=compose.yaml:compose.tuners.yaml:compose.mariadb.yaml docker compose --profile mariadb up -d --build
```

## 永続データ・BonCasLink

各設定テンプレートは `config/`。起動時、recisdb-proxy はBonCasLink設定を `/data/recisdb-proxy.toml` に出力。`BONCAS_B25_HOST` は必須。空なら起動エラーで終了。`BONCAS_4K_HOST` が空なら `[mmttlv]` セクションを出力しない。

EPGStation のDB・一般一時ファイルは `data/epgstation`、ログは `data/epgstation-logs`、サムネイルは `data/epgstation-thumbnail`、dropログは `data/epgstation-drop`、録画一時領域と完成録画は `RECORDED_DIR` 下に保存。KonomiTV のDB・ログは `data/konomitv` / `data/konomitv-logs`。KonomiTV は録画設定パスへ `/host-rootfs` を付けるため、録画ディレクトリを `/host-rootfs/recorded` へbind mount。

ログ設定3ファイルは起動時にフォーク内 `*.sample.yml` から生成。サンプルの `%OperatorSystem%` 等はEPGStationが `/app/logs/...` へ展開し、`/app/logs` はホストへ永続化。

BonCasLink は平文・無認証。BonCasServerのポートをLAN/VPNに限定し、ファイアウォールで録画ホストだけ許可。Mirakurun APIとWeb UIをインターネットへ直接公開しない。

## KonomiTV ネットワーク

KonomiTV はbridgeで稼働し、`mirakurun_url` はCompose DNS名 `recisdb-proxy` を使う。フォーク起動コードはAkebiを `0.0.0.0:server.port` で待受け、同一コンテナ内 `127.0.0.77:(server.port + 10)` のUvicornへ中継する。`<IPをハイフン区切り>.local.konomi.tv` はクライアントがAkebiへ送るHost名。サーバーがコンテナIPからURLを組み立てる実装ではないため、bridgeの172.x IPへの誤リダイレクトなし。ホスト公開ポート `${KONOMITV_PORT}:7000` が外部入口。

根拠: `KonomiTV/server/KonomiTV.py:149-180` (Akebi待受・`port + 10`転送)、`server/app/routers/MaintenanceRouter.py:59-62` (外部Hostと内部Hostの判定)、`config/config.yaml.example:27,57` (recisdb接続先・server.port)。

## トラブルシュート

- B25復号不可: `BONCAS_B25_HOST:BONCAS_B25_PORT` 到達性、サーバーポート、B-CASカード確認。4Kは `BONCAS_4K_HOST:BONCAS_4K_PORT` とdantto4k設定確認。
- チューナー不可視: 対応 `/dev` ノード、`compose.tuners.yaml`、`VIDEO_GID` 確認。追加後 `make tuners` 再実行。
- KonomiTVがMirakurun URLを拒否: `/mirakurun/api/tuners` の `Server: Mirakurun/...` ヘッダーを返す互換版が必要。
- API到達不可: コンテナ間URLは `http://recisdb-proxy:40080/mirakurun`。公開ポートと内部ポートを混同しない。
- B25 / BonCasLink異常: 実行イメージがソース内蔵静的aribb25を使用しているか確認。

## 検証

Dockerなしの静的検査: Compose/設定YAML構文、全シェルの `sh -n`、チューナー生成スクリプトを一時 `/dev` で確認。Docker実機では `docker compose config`、各イメージbuild、ヘルスチェック、デバイス権限、BonCasLink/B25復号、チャンネルスキャン、EPG取得、予約録画、KonomiTV URL判定・再生、GPUエンコード、MariaDB接続を確認。
