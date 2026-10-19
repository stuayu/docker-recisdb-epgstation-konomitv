# docker-recisdb-epgstation-konomitv 構成提案

recisdb-proxy-rs + EPGStation + KonomiTV を Docker Compose で運用し、カードを挿したホストの BonCasRelay から B-CAS / ACAS を共有する構成。

調査日: 2026-10-18 (ローカルの各リポジトリを静的に読んだ結果。実機での疎通は未実施)

## 1. 結論

- コンテナはサービスごとに分け、Compose で束ねる。
- カードサーバーは BonCasRelay。Linux / macOS / Windows に対応し、BonCasLink 互換プロトコルで B-CAS / ACAS を共有する。
- BonCasClient は不要。recisdb-proxy 自身が BonCasLink クライアントを内蔵 (`b25-sys/src/pcsc_shim.rs`、設定は `[b25] boncaslink_server = "host:port"`)。
- コンテナ側に pcscd とカードリーダーは置かない。カード操作 (APDU) だけ LAN 越しに流れる。

```
[カードホスト (Linux / macOS / Windows)]       [録画ホスト (Linux, Docker)]
 B-CAS / ACAS カード                        ┌ recisdb-proxy ── /dev/px4video* (チューナー)
       │                                    │   [b25] boncaslink_server ─┐
 BonCasRelay :6900 ◀──── BonCasLink ────────┤   [mmttlv] boncaslink_server ─┘
       │                                    │   :40080 Mirakurun 互換 API
 Web 設定 :6980 (localhost)                 ├ epgstation ── recisdb-proxy
                                            └ konomitv ──── recisdb-proxy
```

BonCasRelay は APDU から B-CAS / ACAS を自動判定し、既定ポート 6900 で振り分ける。recisdb-proxy の B25 用・4K 用接続先も同じ `host:6900` にできる。

## 2. 各コンポーネントの役割と現状

### BonCasRelay

- カードを挿したホストで起動。Linux / macOS / Windows 対応。
- 既定の自動振り分けポートは 6900。APDU を判定して B-CAS / ACAS リーダーへ振り分ける。
- `--allow 192.168.1.20/32` のように録画ホストの IP だけ許可する。固定ポートが必要なら `--reader-port READER=PORT` または INI `[CardPort]` を使う。
- Web 設定画面は `http://127.0.0.1:6980/`。リーダー判定、振り分け先、接続中クライアントを確認できる。
- 通信は平文・無認証。

### recisdb-proxy (stuayu/recisdb-proxy-rs)

- px4_drv 系チューナーを直接扱い、チューナーの取り合いを一元管理。
- `/mirakurun/api/*` に Mirakurun 互換 API (`recisdb-proxy/src/web/mirakurun.rs`)。
- B25 デコードはサーバー側で実施。カード参照先に BonCasLink / PC/SC を選べる。
- Docker 対応は未整備 (Dockerfile なし)。Linux バイナリは glibc 2.34 / OpenSSL 3 が要件 → Debian bookworm / Ubuntu 24.04 系が候補。
- システムに共有 `libaribb25.so` があると pcsc_shim が効かない。同梱 (静的) ビルドを使う。
- 4K の `[mmttlv] boncaslink_server` は dantto4k 用。BonCasRelay の APDU 自動振り分けポートへ接続できる。

### EPGStation (stuayu フォーク)

- `docs/EPGSTATION_COMPAT.md` に必要な Mirakurun 互換 API は実装済みとある。
- 接続先: `mirakurunPath: http://recisdb-proxy:40080/mirakurun/`。

### KonomiTV (stuayu フォーク)

- `Dockerfile` と `docker-compose.example.yaml` を流用。
- recisdb-proxy の Mirakurun API を利用。
- 起動時チェックは `GET /api/tuners` の `Server` ヘッダーを確認。互換版で `Server: Mirakurun/<互換バージョン>` を返す必要がある。
- 接続先: `mirakurun_url: http://recisdb-proxy:40080/mirakurun`。

## 3. 推奨する進め方

1. カードホストで BonCasRelay を起動し、録画ホストの IP だけ許可する。
2. recisdb-proxy をコンテナ化し、BonCasRelay 経由で地デジ・BS を復号できることを確認する。
   - `devices: /dev/px4video*`、`[b25] boncaslink_server` を設定。
   - 設定ファイル・DB・ロゴはボリュームへ保存。
3. recisdb-proxy の Mirakurun 互換 API に `Server: Mirakurun/<互換バージョン>` を付け、KonomiTV のライブ視聴を確認する。
4. EPGStation を接続し、予約録画を確認する。
5. GPU エンコード、4K (dantto4k + ACAS) を追加。4K 用 `[mmttlv] boncaslink_server` は同じ BonCasRelay `host:6900` を指定する。

## 4. 決定済み事項

- カードサーバーは BonCasRelay。OS 不問 (Linux / macOS / Windows)。
- B-CAS と ACAS は BonCasRelay の自動振り分けポート 6900 を共有。固定ポートを使う構成では各リーダー用ポートを指定し、`.env` の接続先も合わせる。
- カードサーバーと録画サーバーが拠点をまたぐ場合は WireGuard / Tailscale 経由にする。
- EPGStation の DB は MariaDB 固定 (`mariadb:latest`)。接続・パスワード設定は自動化。
- EDCB は任意サービスとして追加 (初回既定ではい)。BonDriver_LinuxMirakc 経由で recisdb-proxy に接続。実装・根拠は [EDCB ガイド](EDCB.md#edcb-と-material-webui-任意初回既定ではい)、検証範囲は[開発・検証記録](DEVELOPMENT.md#この変更の検証範囲)を参照。
- KonomiTV の GPU エンコードは Intel QSV / VAAPI / NVIDIA NVENC から選ぶ。

## 5. セキュリティ上の注意

- BonCasLink 互換通信は平文・無認証。BonCasRelay の `--allow` とファイアウォールで録画ホストだけ許可し、インターネットへ公開しない。
- BonCasRelay の Web UI は既定でループバック待受。外部待受には token を設定する。
- recisdb-proxy のダッシュボード、EPGStation、KonomiTV も外部公開時は VPN 越しにする。
