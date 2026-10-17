# dtv-stack 構成提案

recisdb-proxy-rs + EPGStation + KonomiTV を Docker Compose で動かし、B-CAS / ACAS カードは
別マシンの BonCasServer から BonCasLink プロトコルで借りる構成の提案。

調査日: 2026-10-18 (ローカルの各リポジトリを静的に読んだ結果。実機での疎通はまだ行っていない)

## 1. 結論

- コンテナは「1 つにまとめる」のではなく、サービスごとに分けて Compose で束ねる。
- **BonCasClient は不要。** recisdb-proxy 自身が BonCasLink クライアントを内蔵している
  (`b25-sys/src/pcsc_shim.rs`、設定は `[b25] boncaslink_server = "host:port"`)。
  BonCasClient は Windows の WinSCard.dll 置き換えなので Linux コンテナでは使えない。
- コンテナ側には pcscd もカードリーダーも置かない。カード操作 (APDU) だけが LAN 越しに流れる。

```
[カードサーバー (Windows)]                 [録画サーバー (Linux, Docker)]
 BonCasServer (MT6768 版)                   ┌ recisdb-proxy ── /dev/px4video* (チューナー)
  ├ B-CAS リーダー :6900  ◀── APDU/TCP ──── │   [b25] boncaslink_server
  └ ACAS  リーダー :6902  ◀── APDU/TCP ──── │   [mmttlv] boncaslink_server (dantto4k, 4K)
                                            │   :40080 Mirakurun 互換 API /mirakurun/api/*
                                            ├ epgstation ── mirakurunPath → recisdb-proxy
                                            │   (+ mariadb もしくは sqlite)
                                            └ konomitv ──── mirakurun_url → recisdb-proxy
                                                (GPU パススルー: QSV / VAAPI / NVENC)
```

## 2. 各コンポーネントの役割と現状

### recisdb-proxy (stuayu/recisdb-proxy-rs)
- px4_drv 系チューナーを直接扱い、チューナーの取り合いを一元管理する。
- `/mirakurun/api/*` に Mirakurun 互換 API を持つ (`recisdb-proxy/src/web/mirakurun.rs`)。
- B25 デコードはサーバー側で実施。カードの参照先は BonCasLink / PC/SC を選べる。
- BonCasLink 通信のタイムアウト: カード接続 3 秒、APDU 5 秒 (`docs/BUILD.md`)。
- Docker 対応は未整備 (Dockerfile なし)。Linux バイナリは glibc 2.34 / OpenSSL 3 が要件
  → ベースイメージは Debian bookworm / Ubuntu 24.04 系にする。
- 注意: システムに共有 `libaribb25.so` があると pcsc_shim が効かない。同梱 (静的) ビルドを使う。

### EPGStation (stuayu フォーク)
- `docs/EPGSTATION_COMPAT.md` によると、必要な Mirakurun 互換 API は実装済み。
  ただし **実起動での疎通は未確認** で、EPGStation 側の改修も未コミットの差分が残っている (2026-08-09 時点)。
- 接続先: `mirakurunPath: http://recisdb-proxy:40080/mirakurun/`

### KonomiTV (stuayu フォーク)
- `Dockerfile` と `docker-compose.example.yaml` が同梱されているので、それを流用する。
- 使う Mirakurun API: `/api/tuners`, `/api/services`, `/api/programs`,
  `/api/services/{id}/stream`, `/api/services/{id}/logo`。
- **起動時チェックで止まる問題がある。** `server/app/config.py` は `GET /api/tuners` の
  レスポンスヘッダー `Server` から `Mirakurun/x.y.z` か `mirakc/x.y.z` を読み、
  バージョンが取れないと「Mirakurun の URL ではありません」としてエラーにする。
  recisdb-proxy の互換 API は現状 `Server` ヘッダーを返していない (要確認・要対応)。
- 接続先: `mirakurun_url: http://recisdb-proxy:40080/mirakurun`

### BonCasServer (MT6768/BonCasLink)
- Windows (MFC) 専用。B-CAS / ACAS への APDU 自動振り分け、リーダーごとのポート割り当てに対応済み。
- 通信は暗号化されない。

## 3. 推奨する進め方

1. **カードサーバーの OS を決める** (下記「決めること」)。
2. **recisdb-proxy 単体をコンテナ化** し、BonCasServer 経由で地デジ・BS がデコードできることを確認する。
   - `devices: /dev/px4video*`、`[b25] boncaslink_server` を設定。
   - 設定ファイル・DB・ロゴはボリュームに出す。
3. **KonomiTV 互換の穴埋め** (recisdb-proxy 側)
   - `/mirakurun/api/*` の応答に `Server: Mirakurun/<互換バージョン>` を付ける。
   - KonomiTV の実起動でライブ視聴まで確認する。
4. **EPGStation を接続** し、予約録画 1 件を通して確認する。録画は優先度を高く (`X-Mirakurun-Priority`) して、
   KonomiTV の視聴に奪われないことを確認する。
5. GPU エンコード、4K (dantto4k + ACAS) は最後に足す。

## 4. 決めること

- カードサーバーは Windows か Linux か。
  - Windows: BonCasServer (MT6768 版) をそのまま使う。最短。
  - Linux: BonCasServer は動かない。pcscd + BonCasLink 互換サーバーを小さく自作する
    (例: recisdb-proxy-rs に `boncaslink-server` バイナリを追加) のが現実的。Wine は勧めない。
- カードサーバーと録画サーバーは同じ LAN か。拠点をまたぐなら WireGuard / Tailscale 経由にする。
- EPGStation の DB は MariaDB か SQLite か。
- KonomiTV のエンコードに使う GPU (Intel QSV / VAAPI / NVIDIA NVENC)。

## 5. セキュリティ上の注意

- BonCasLink は平文で、認証もない。ポートに届いた相手は誰でもカードを使える。
  6900 / 6902 番ポートは LAN 内、できれば録画サーバーの IP だけに絞り、インターネットには絶対に公開しない。
- recisdb-proxy のダッシュボード (40080) と EPGStation / KonomiTV も、外から使うなら VPN 越しにする。
