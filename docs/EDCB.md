# EDCB と EPGStation 連携

## EDCB と Material WebUI (任意、初回既定ではい)

`./setup.sh` が選択・ポート・実行 UID/GID・仮想チューナー数を設定します。非対話では `EDCB=yes ./setup.sh --yes`、無効にする場合は `EDCB=no ./setup.sh --yes` を指定します。選択は `SETUP_EDCB` に保存します。設定だけなら `--reconfigure` を付け、`make build && make up` で反映します。EDCB 無効時は EDCB 用サービス・HTTPS 経路を読み込みません。KonomiTV のバックエンドは引き続き recisdb-proxy の Mirakurun 互換 API です。

EDCB `my-build` を Ubuntu 24.04 LTS で `make -C Document/Unix` / `install_u` によりビルドします。Lua は Ubuntu noble の `liblua5.2-dev` / `lua-zlib` を利用します。Material WebUI は本家 [EMWUI/EDCB_Material_WebUI](https://github.com/EMWUI/EDCB_Material_WebUI) の `E3` ブランチから `HttpPublic` と `Setting` を組み込みます。WebUI は `/E3/` で配信されます (`http://<録画ホストIP>:5510/E3/`)。E3 の導入手順 (`HttpPublic` と `Setting` の配置、`HttpPort=5510`、`HttpNumThreads` の増設) と EDCB 側の要件 (Lua 5.2) を確認し、`configure.py` は `HttpNumThreads=50` を初期値にします。E3 が呼ぶ EDCB Lua API は `stuayu/EDCB` の `my-build` の `Document/Readme_Mod.txt` に記載されたものだけで、`FindFilePlain` は `FindFile` が無いときの代替です。根拠: [E3 導入](https://github.com/EMWUI/EDCB_Material_WebUI/blob/E3/README.md#導入)、[Readme_Mod.txt](https://github.com/stuayu/EDCB/blob/my-build/Document/Readme_Mod.txt)、[util.lua の FindFile 分岐](https://github.com/EMWUI/EDCB_Material_WebUI/blob/E3/HttpPublic/E3/util.lua)。ソースは Docker ビルド時に取得し、このリポジトリには複製しません。EpgTimerSrv はコンテナ内でフォアグラウンド常駐し、tini と `restart: unless-stopped` が管理します。systemd は不要です。停止猶予は上流の unit 例に合わせて 50 秒です。根拠: [HowToBuild.txt の Linux 節](https://github.com/stuayu/EDCB/blob/my-build/Document/HowToBuild.txt#L104-L200)、[Unix/Makefile](https://github.com/stuayu/EDCB/blob/my-build/Document/Unix/Makefile)、[WebUI の配置](https://github.com/EMWUI/EDCB_Material_WebUI/blob/E3/README.md#導入)。

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
| `[BonDriver_LinuxMirakc.so]` | `Count=EDCB_TUNER_COUNT` (初期値 2、スキャン成功後に公開中の物理デバイス数へ同期)、`Priority=1` (EDCB 内部 ID)、`GetEpg=1`、`EPGCount=1` |
| `[EPG_CAP]` | 毎日 06:00 / 18:00、両方有効 |
| `[TVTEST]` | `Num=1`、`0=BonDriver_LinuxMirakc.so` |
| `[REC_DEF]` | `RecMode=3` (指定サービスのみ・B25 処理なし) |
| `EpgDataCap_Bon.ini [SET]` | `Scramble=0`、`EMM=0` |
| `BonDriver_LinuxMirakc.so.ini [GLOBAL]` | `SERVER_HOST=recisdb-proxy`、`SERVER_PORT=40080`、`SERVER_TYPE=http`、`DECODE_B25=0`、`PRIORITY=2`、`SERVICE_SPLIT=1` |

編集する INI と ChSet は `config/edcb/` に置き、EDCB の既定パスからリンクします。EDCB の INI 保存は同じファイルを書き換えるため、リンク先が更新されます (`Common/PathUtil.cpp` の `WritePrivateProfileString`)。予約・録画履歴・自動予約・EPG・ログ・WebUI コードは `data/edcb/` に残します。旧設定は setup.sh がコピーし、起動時に旧パスを `.pre-config-migration` として残してからリンクします。録画は各録画先の `edcb/` に保存します。UID/GID を合わせて起動し、既存録画全体の所有者は変更しません。チューナー数や保存先を変更した場合は、録画がないときに EDCB を停止し、`make regen-config SERVICE=edcb` の差分を確認してから `make up` を実行してください。既存プリセット・予約に保存された個別設定は E3 でも確認してください。

recisdb-proxy がサーバー側で復号し、互換 API の `decode` クエリ値は解釈されません。EDCB 側に B25 ライブラリーは導入せず、上記のアプリ設定と既定予約モードで CAS 処理を無効にします。WebUI で別の録画プリセットを追加する場合も「B25 処理なし」を選びます。根拠: recisdb [mirakurun.rs:1093-1108](https://github.com/stuayu/recisdb-proxy-rs/blob/feature/proxy/recisdb-proxy/src/web/mirakurun.rs#L1093-L1108)、EDCB [CommonDef.h:22-25](https://github.com/stuayu/EDCB/blob/my-build/Common/CommonDef.h#L22-L25)、[TunerBankCtrl.cpp:793-802](https://github.com/stuayu/EDCB/blob/my-build/EpgTimerSrv/EpgTimerSrv/TunerBankCtrl.cpp#L793-L802)、[AppSetting.cpp:37-40](https://github.com/stuayu/EDCB/blob/my-build/EpgDataCap_Bon/EpgDataCap_Bon/AppSetting.cpp#L37-L40)。

その他の設定キーの根拠: EDCB [PathUtil.cpp:401-409,479以降](https://github.com/stuayu/EDCB/blob/my-build/Common/PathUtil.cpp#L401-L409)、[ReserveManager.cpp:24-47](https://github.com/stuayu/EDCB/blob/my-build/EpgTimerSrv/EpgTimerSrv/ReserveManager.cpp#L24-L47)、[EPG 時刻設定](https://github.com/stuayu/EDCB/blob/my-build/EpgTimerSrv/EpgTimerSrv/EpgTimerSrvSetting.cpp#L70-L105)、[HTTP 設定](https://github.com/stuayu/EDCB/blob/my-build/Document/Readme_Mod.txt#L848-L869)、[録画プリセット](https://github.com/stuayu/EDCB/blob/my-build/EpgTimerSrv/EpgTimerSrv/EpgTimerSrvMain.cpp#L3247-L3268)。

### ChSet の自動投入・再取得

1. Web 認証が有効な設定では起動時に recisdb-proxy の永続 DB を読み取り専用で開き、`web_auth_config.auth_token` を取得します。認証無効時は token なしで接続します。
2. `/api/client-view/targets` で登録済みドライバーを列挙し、`/api/client-view/files/chset4?tuner=...` と `chset5?tuner=...` を取得します。認証有効時だけ token を付けます。
3. `/mirakurun/api/services` の順番に合わせて空間・チャンネル番号を変換し、サービスを統合します。`BonDriver_LinuxMirakc(LinuxMirakc).ChSet4.txt` と `ChSet5.txt` を `config/edcb/Setting` に UTF-8 BOM で保存します。BNDP 用の ChSet4 をそのまま置くことはできません。
4. 未スキャン・認証失敗・不正応答なら既存ファイルを保持し、ログへ理由を出します。初回は ChSet なしでも WebUI を起動します。`make scan` で登録から再試行できます。ChSet 再取得だけ行う場合は `make edcb-chset` を使います。

`make edcb-chset` は EDCB を停止し、一時コンテナで再取得・番号変換・既存ファイルの日時付きバックアップを行い、EDCB を再起動します。録画中は実行しないでください。取得失敗時も既存 ChSet を残して EDCB を再起動します。`make scan` は成功後にこの処理を呼び出します。仮想番号が変わるため、再取得後は既存予約のチャンネルを確認してください。初回の EPG は次の定期取得、または WebUI の EPG 取得操作で読み込みます。recisdb の EPG DB を EDCB に直接コピーする処理ではありません。

根拠: recisdb [client_view.rs:34-123,244-290](https://github.com/stuayu/recisdb-proxy-rs/blob/feature/proxy/recisdb-proxy/src/web/api/client_view.rs#L244-L290)、[ChSet の列形式](https://github.com/stuayu/recisdb-proxy-rs/blob/feature/proxy/recisdb-proxy/src/web/channel_files.rs#L196-L259)、[token の保存](https://github.com/stuayu/recisdb-proxy-rs/blob/feature/proxy/recisdb-proxy/src/database/mod.rs#L2017-L2037)、EDCB [ChSet のファイル名](https://github.com/stuayu/EDCB/blob/my-build/BonCtrl/ChSetUtil.cpp#L16-L34)、上流 BonDriver [GetTunerName](https://github.com/matching/BonDriver_LinuxMirakc/blob/main/src/BonDriver_LinuxMirakc.cpp#L301-L311)。

### ポート・併用・バージョン固定

`.env` の `EDCB_WEB_PORT` (既定 5510) を内部 5510 へ、HTTPS 併用時は `EDCB_HTTPS_PORT` (既定 8553) を Akebi の内部 8553 へ公開します。EDCB の TCP 制御ポートは公開しません。EDCB の HTTP ACL は RFC1918 LAN を許可します。公開 IPv4 / IPv6 の直接アクセスは初期 ACL では対象外です。各 WebUI と同様、信頼できる LAN/VPN 内で使用してください。

KonomiTV と EPGStation の接続先は変えません。全サービスのストリームは recisdb-proxy のチューナープールで調停されます。ただし各録画アプリの予約スケジューラーは独立しており、合計の同時録画・視聴が物理チューナー数を超えると確保失敗や視聴停止が起きます。LinuxMirakc の `PRIORITY=2` は EPG 取得にも適用され、BNDP のように操作ごとの優先度・排他フラグを指定する構成ではありません。短い予約録画と KonomiTV 同時視聴で確認してください。Material WebUI の基本の番組表・予約管理を対象とし、トランスコード配信の追加ツール・局ロゴ登録は上流の手順が別途必要です。

ビルド引数は `.env` の `EDCB_REF=my-build`、`EDCB_WEBUI_REPO=https://github.com/EMWUI/EDCB_Material_WebUI.git`、`EDCB_WEBUI_REF=E3`、`EDCB_BONDRIVER_REF=main` から渡します。コミット固定する場合は各値を完全なコミット SHA に置き換え、`docker compose build --no-cache edcb` を実行します。ブランチ追従時の更新にも `--no-cache` が必要です (Docker はブランチ先端の変更だけではソース取得レイヤーを無効にしません)。上流ソース変更時は互換補正の検査が失敗することがあり、`patch-driver.py` の見直しが必要です。




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
