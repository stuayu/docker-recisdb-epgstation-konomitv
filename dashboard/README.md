# EDCB ダッシュボード

Vue 3 / Vite / TypeScript / SCSS の画面本体です。Node 24 を使用します。
画面本体の開発手順と、EDCB イメージへの組み込み方法を記載します。

## ファイル構成

```text
dashboard/
  .gitignore
  .npmrc
  README.md
  package.json
  package-lock.json
  tsconfig.json
  vite.config.ts
  index.html
  src/
    main.ts
    App.vue
    App.test.ts
    style.scss
    components/
      ServicePanel.vue
      ProgrammeList.vue
    composables/
      useDashboard.ts
    lib/
      config.ts
      config.test.ts
      urls.ts
      urls.test.ts
      edcb.ts
      edcb.test.ts
      status.ts
      status.test.ts
      format.ts
  mock/
    dashboard.json
    EnumReserveInfo.json
    EnumRecInfo.json
    EnumTunerReserveInfo.json
    EnumService.json
  tooling/
    mockPlugin.ts
    licenses.ts
  dist/                         # ビルド生成物、Git 管理対象外
    index.html
    dash-assets/                # ハッシュ付き資産
  qa-output/verification.log    # 検証コマンド全文、Git 管理対象外
```

## 開発と検証

```sh
cd dashboard
npm ci
npm run typecheck
npm test
npm run build
npm run dev
# 本番ビルドをモックと組み合わせる場合 (dev と同時には起動しない)
npm run preview:mock
```

開発・モックプレビューは `http://127.0.0.1:5179/`。ポートが使用中なら終了します。
`npm run preview:mock` は先にビルドが必要です。モックは Vite ミドルウェアだけで配信し、dist には入りません。
`mock/*.json` は予約 8 件、録画 6 件、物理チューナー 8 本と「チューナー不足」の疑似チューナーを含みます。
固定サンプルの基準時刻は `2026-10-18T21:48:07+09:00`。サーバー起動時刻へ日時を移動し、起動時に 1 件録画中にします。
長時間動かすと予約は通常どおり進みます。最初の状態へ戻すには開発サーバーを起動し直します。
サービスの到達確認は実 URL に対して行うため、モック表示でも各システムが起動していなければ「応答なし」になります。
`no-cors` の fetch が解決すれば、HTTP ステータスを問わず「稼働中」です。HTTP 500、認証応答、opaque 応答も区別しません。
HTTPS ページから HTTP への確認は送信せず「未確認」です。

フォントは npm から同梱し、外部 CDN を使用しません。IBM Plex Sans JP は 400/500/700 の unicode-range 分割を維持します。
Archivo は `@fontsource-variable/archivo/wdth.css` を使い、パッケージの `metadata.json` と CSS に幅軸 62–125 があることを確認済みです。
時計は `wdth=75`、数字は等幅です。第三者ライセンスは `dist/dash-assets/third-party-licenses-<hash>.txt` に出力します。

## 実行時の設定

`HttpPublic/dashboard.json` を生成してください。JSONC ではなく JSON です。
設定例は `mock/dashboard.json`。無効なサービスは配列から除外します。ポートは 1–65535 の整数です。
`host` / `httpsHost` はスキームやポートを含まないホスト名または IPv4 / IPv6 です (IPv6 は括弧なし)。
`httpsHost` は HTTPS 無効時に null にできます。ただし HTTPS だけのサービスを残した状態では不正設定になります。
`local` と `http` / `https` は同じサービスに混在できません。

設定が欠落・不正・取得失敗なら、再生成コマンドを表示します。サービスの既定一覧を捏造せず、同一オリジンの EDCB 情報と E3 / legacy 導線だけを残します。
設定が正常で `edcb.api=false` の場合は EDCB API へアクセスしません。
設定はページ起動時に読み込みます。再生成後はページを再読み込みしてください。

リンク決定は `src/lib/urls.ts`。現在の方式と同じ接続には `location.hostname`、別方式には `host` / `httpsHost` を使います。
副リンクも実 URL を持ちます。パネルの主リンクは 1 個の anchor を CSS で全面へ広げ、副リンクを独立させています。
ローカル専用サービスはリンクにせず、アドレスとコピーボタンを表示します。
HTTP の非セキュアコンテキスト等で Clipboard API が使えない場合は、文字列を選択して手動コピーできます。

## EMWUI JSON の根拠

確認した E3 コミット: `7c44e03d8b4e9d0f16ccad553343d42e3d524af3`。
以下は描画で必要なフィールドの抜粋です。他のフィールドが含まれていても受け付けます。

- [EnumReserveInfo](https://github.com/EMWUI/EDCB_Material_WebUI/blob/7c44e03d8b4e9d0f16ccad553343d42e3d524af3/HttpPublic/api/EnumReserveInfo): `edcb.GetReserveData()` を JSON にします。
- [EnumRecInfo](https://github.com/EMWUI/EDCB_Material_WebUI/blob/7c44e03d8b4e9d0f16ccad553343d42e3d524af3/HttpPublic/api/EnumRecInfo): id 未指定では `edcb.GetRecFileInfoBasic()` の一覧です。詳細取得や録画ファイルの読み込みは行いません。
- [EnumTunerReserveInfo](https://github.com/EMWUI/EDCB_Material_WebUI/blob/7c44e03d8b4e9d0f16ccad553343d42e3d524af3/HttpPublic/api/EnumTunerReserveInfo): `edcb.GetTunerReserveAll()` を JSON にします。reserveList の中身は予約オブジェクトではなく数値の予約 ID です。
- [util.lua の ConvertJson / ResponseJson](https://github.com/EMWUI/EDCB_Material_WebUI/blob/7c44e03d8b4e9d0f16ccad553343d42e3d524af3/HttpPublic/api/util.lua): 日付テーブルは `YYYY-MM-DDTHH:mm:ss+09:00`、無効 recMode=5 は `recEnabled=false` と表示用 recMode に変換します。count 指定がない場合は配列を直接返します。count>0 の場合だけ `{total,index,count,items}` に包まれるため、本画面は count を送信しません。
- [EnumService](https://github.com/EMWUI/EDCB_Material_WebUI/blob/7c44e03d8b4e9d0f16ccad553343d42e3d524af3/HttpPublic/api/EnumService): EPG 状態の判別に追加使用します。サービス一覧、または `{ "err": "EPGデータを読み込み中、または存在しません" }` を返します。空配列またはこのエラーなら EPG 未取得・読み込み中の文言を表示し、通信失敗とは区別します。

```json
[
  {
    "reserveID": 1,
    "title": "番組名",
    "startTime": "2026-10-18T21:30:00+09:00",
    "durationSecond": 3600,
    "stationName": "NHK 総合",
    "eid": 100,
    "overlapMode": 0,
    "recSetting": { "recEnabled": true, "recMode": 1 }
  }
]
```

録画履歴は `[{ "id": 100, "title": "番組名", "startTime": "2026-10-18T19:30:00+09:00", "durationSecond": 1800, "serviceName": "NHK 総合" }]`。
チューナーは `[{ "tunerID": 65537, "tunerName": "BonDriver_LinuxMirakc.so", "reserveList": [1] }]`。
EPG サービス一覧は `[{ "onid": 32736, "tsid": 32736, "sid": 1024, "service_name": "NHK 総合" }]`。
配列以外や壊れたレコード、日時不正は取得失敗として扱い、誤った 0 件表示を避けます。

## 録画中判定

EnumTunerReserveInfo は「割当表」であり、実プロセスの録画開始・成功を保証しません。
EDCB の [ReserveManager.cpp / GetTunerReserveAll](https://github.com/stuayu/EDCB/blob/6931b849f1da4242fdb2b29105c3b851535cb4bd/EpgTimerSrv/EpgTimerSrv/ReserveManager.cpp#L136) で、予約 ID を列挙し、最後に tunerID=4294967295 の「チューナー不足」を追加することを確認しました。この疑似チューナーは物理一覧と REC 判定から除外します。

本画面の REC 条件は、有効 (`recEnabled=true`) かつ録画モード 0–3、物理チューナーへの割当あり、`startTime <= 現在時刻 < startTime + durationSecond`。
無効予約・視聴専用モード 4・割当失敗は録画中にしません。件数は予約単位なので、同一チューナーで同時録画が複数あればランプ数と異なります。
予約総数には無効予約も含め、次の録画と 5 件の予定は有効な録画予約を対象にします。5 件には録画中を含みます。
JST を明示して表示するため、端末のタイムゾーンが違っても日時は変わりません。

画面に「録画状態は予約の割当・時刻から判定」と表示します。録画マージン・チューナープロセス停止・実ファイル生成は判定しません。
指定 API だけでは実録画成功を保証できないため、配備時は実録画・ログと比較してください。
API は 60 秒ごと、サービス確認は 30 秒ごと、タブが前面に戻ったときは両方を更新します。

## 第 2 段階への引き継ぎ

### 組み込み実装

`docker/edcb/Dockerfile` の Node 24 ステージで `npm ci` → `npm run typecheck` → `npm test` → `npm run build` を実行します。`docker/edcb/http_public.py` がビルド済み HTML を `dashboard-index.lua` の長括弧文字列へ埋め込み、`HttpPublic/index.html` に配置します。区切り文字が本文に現れた場合は `=` を増やして衝突を避けます。Vite の `dist/index.html` 自体はプレビュー用の生 HTML のままです。

配信方式の根拠は、[EDCB HttpServer.cpp](https://github.com/stuayu/EDCB/blob/6931b849f1da4242fdb2b29105c3b851535cb4bd/EpgTimerSrv/EpgTimerSrv/HttpServer.cpp#L111) の `.html` を Lua として実行する設定、[標準トップ](https://github.com/stuayu/EDCB/blob/6931b849f1da4242fdb2b29105c3b851535cb4bd/ini/HttpPublic/index.html) の長括弧文字列と `mg.write`、[EMWUI E3](https://github.com/EMWUI/EDCB_Material_WebUI/blob/7c44e03d8b4e9d0f16ccad553343d42e3d524af3/HttpPublic/E3/index.html) の `CreateContentBuilder` と `mg.write` です。`/` は CivetWeb の既定 `index_files` によって `index.html` を選びます。ラッパーは標準トップの HEAD / Content-Length / keep-alive の扱いを踏襲し、`Content-Type: text/html; charset=utf-8` と `Cache-Control: no-cache` を返します。

標準トップを `/server.html` に保持し、既存 `/legacy/` メニューへリンクを追加します。ルートのまま保持するため、標準トップにある相対リンクも維持されます。`/E3/`、`/legacy/`、`api/`、`favicon.ico` はそのまま配置します。

フォントの MIME はビルド時と起動時に `ContentTypeText.txt` の既存項目を保持して `.woff2\tfont/woff2`、`.woff\tfont/woff` を設定します。[ParseContentTypeText](https://github.com/stuayu/EDCB/blob/6931b849f1da4242fdb2b29105c3b851535cb4bd/Common/ParseTextInstances.cpp#L334) はタブ区切りを読み、HttpServer.cpp が `extra_mime_types` へ渡します。[CivetWeb get_mime_type](https://github.com/stuayu/EDCB/blob/6931b849f1da4242fdb2b29105c3b851535cb4bd/EpgTimerSrv/EpgTimerSrv/civetweb.c#L8322) は追加定義を既定 MIME より優先します。JS / CSS / JSON は既定 MIME、静的ファイルのキャッシュ期間も既定の `static_file_max_age=3600` を使用します。

setup / `make update` / `make regen-config SERVICE=edcb` は `.env` から `data/edcb/dashboard.json` を再生成します。LAN IP の検出は setup の既存手順 (route の `src` → `hostname -I` → `localhost`) を `scripts/dashboard.py` で共用します。起動時に `HttpPublic/dashboard.json` → `../dashboard.json` のリンクを作るため、JSON がない場合もリンク先は欠落したままになり、画面が既存の設定エラーを表示します。表示名は `DASHBOARD_TITLE` で指定します。

HTTPS 無効時は `httpsHost=null` とし、HTTPS 専用の KonomiTV を一覧から除外します。KonomiTV 本体の稼働状態は変更しません。BonCasRelay は同梱 local 構成だけをループバックのアドレスで表示します。

以下は第 1 段階で確認した配信条件と実装上の注意点です。

出力は `dist/index.html` と `dist/dash-assets/` 内のハッシュ付き JS、CSS、WOFF2、WOFF、ライセンスです。
`base: './'`。JSON とモックは dist に入りません。`E3/`、`legacy/`、`api/`、`favicon.ico` を維持してください。
現在のイメージは `/opt/edcb-defaults/HttpPublic/` を起動時に `/var/local/edcb/HttpPublic/` へ上書きコピーするため、イメージ側と実配信側の両方に注意してください。

**重要: 生の Vite index.html を EDCB にコピーするだけでは動きません。**
[HttpServer.cpp](https://github.com/stuayu/EDCB/blob/6931b849f1da4242fdb2b29105c3b851535cb4bd/EpgTimerSrv/EpgTimerSrv/HttpServer.cpp#L111) は `lua_script_pattern` を `**.lua$|**.html$|<root>/api/*$` に設定しています。
[EDCB 標準 index.html](https://github.com/stuayu/EDCB/blob/6931b849f1da4242fdb2b29105c3b851535cb4bd/ini/HttpPublic/index.html) も拡張子は HTML ですが、実体は Lua です。
第 2 段階で `dist/index.html` を Lua の長括弧文字列に包み、UTF-8 の応答ヘッダーと本文を `mg.write` で出す必要があります。
生 HTML の Vite 出力は開発・プレビュー用として維持してください。HTML を包む長括弧の区切りは、HTML 本文と衝突しないものを選びます。

組み込み側で行う処理:

1. Node 24 で `npm ci && npm run build`。
2. `dist/dash-assets/` を `HttpPublic/dash-assets/` にコピー。
3. 上記 Lua ラッパーを付けた index.html を `HttpPublic/index.html` に置く (HTTP HEAD の扱いと Content-Length は EDCB 標準実装を踏襲)。
4. 実環境の有効サービス・ポートから `HttpPublic/dashboard.json` を生成。モック設定を本番へコピーしない。
5. 実機で `/`、`/E3/`、`/legacy/`、`/api/*?json=1`、フォント・JS のレスポンスを確認。

### Content-Type

確認した EDCB コミット: `6931b849f1da4242fdb2b29105c3b851535cb4bd`。
[CivetWeb の MIME 定義](https://github.com/stuayu/EDCB/blob/6931b849f1da4242fdb2b29105c3b851535cb4bd/EpgTimerSrv/EpgTimerSrv/civetweb.c#L8187) には `.json=application/json`、`.js=application/javascript`、`.woff2=application/font-woff2`、`.woff=application/font-woff` があります。
JSON と JS は既定で対応済みです。WOFF2 は旧来の MIME 名なので、現行の `font/woff2` を明示するなら ContentTypeText.txt に拡張子と MIME をタブ区切りで追加してください。
[既定の ContentTypeText.txt](https://github.com/stuayu/EDCB/blob/6931b849f1da4242fdb2b29105c3b851535cb4bd/ini/ContentTypeText.txt) は TS 等だけです。
[HttpServer.cpp](https://github.com/stuayu/EDCB/blob/6931b849f1da4242fdb2b29105c3b851535cb4bd/EpgTimerSrv/EpgTimerSrv/HttpServer.cpp#L101) がこのファイルを `extra_mime_types` へ渡すことを確認しました。

```text
.json	application/json
.js	application/javascript
.woff2	font/woff2
.woff	font/woff
```

上の区切りは実際のタブです。既存の項目は保持してください。設定読み込みは HTTP サーバー起動時なので、変更後の反映とレスポンスは第 2 段階で確認が必要です。

## 検証記録と未確認事項

Node 24.18.0 / npm 12.0.2。型検査と Vitest (データ変換 + happy-dom による Vue の状態遷移) 52 件成功。
本番ビルドとモック HTTP 応答を確認しました。最終出力は `du -sh dist` で `11M` (ファイルの合計 9,978,435 bytes、751 ファイル)。JS は約 84.75 kB、CSS は約 324.68 kB、残りの主な容量は同梱フォントです。
指定コマンドの生の出力は `qa-output/verification.log` に保存しています (Git 管理対象外)。

ブラウザー接続が利用できず、独立した Chromium / WebKit の起動も実行環境の制限で異常終了しました。
PC 1440px、iPad 1024×1366 / 1366px、iPhone 390×844 の実レンダリング、ライト / ダーク双方の目視 QA は未確認です。
レスポンシブ CSS、フォーカス、44px の主要操作領域、safe-area、reduced-motion は実装済みですが、DOM テストは配置や実機タップの保証にはなりません。
EDCB 実機への配置、Lua ラッパー、実機 Content-Type、Akebi 越しの到達確認、実録画との照合は第 2 段階の対象です。
