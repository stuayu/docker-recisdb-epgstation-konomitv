# チューナー自動セットアップの調査・設計

調査日: 2026-10-18。recisdb-proxy-rs のローカルブランチが `feature/proxy` であることを確認し、そのソースを読みました。他リポジトリの変更はありません。以下の `proxy/` は `/Users/ayumu/prog/recisdb-proxy-rs/recisdb-proxy/src/`、`recisdb/` は同リポジトリの `recisdb-rs/src/` を表します。行番号は調査時点のものです。実チューナーによる受信・Docker 上の実行は未検証です。

## 1. Linux での登録表現

- proxy の `dll_path` は DLL に限りません。`/dev/px4video0` 等は CharDev backend、`/dev/dvb/adapter0` または `/dev/dvb/adapter0/frontend0` は DVBv5 backend を選びます。`px4daemon:` は別の daemon backend です。根拠: `proxy/bondriver/mod.rs:50-81`。
- proxy の DVB backend は frontend/demux/dvr の同じ番号を開きます。frontend と demux は読み書き権限が必要です。`adapter0` と `adapter0/frontend0` は同一なので、登録時に同一視します。demux/dvr は別チューナーとして登録しません。根拠: `proxy/bondriver/dvbv5.rs:192-222,594-619`。
- recisdb-rs 本体の CLI は、DVB feature 有効時に `0|0` または `/dev/dvb/adapter0/frontend0` を受け付け、その他は character device として扱います。proxy は recisdb-rs を直接呼び出さず、独自 backend を使います。`0|0` は proxy の登録値には使いません。根拠: `recisdb/tuner/linux/mod.rs:27-60`、`recisdb-proxy/Cargo.toml:33-35`。
- CharDev の公開空間は GR=0 / BS=1 / CS=2、GR は UHF 13〜62 の50個、BS は奇数1〜23の12個、CS は偶数2〜24の12個です。`set_channel()` は空間に応じて ISDB-T/S モードと LNB を切り替えます。チャンネル文字列を `dll_path` に足しません。根拠: `proxy/bondriver/unix.rs:28-89,128-161,298-343`。
- DVB backend は現在 ISDB-T の GR のみです。ISDB-S 対応 frontend でも BS/CS は公開しません。ISDB-T 非対応、firmware 未ロード等は受信できません。PX-S1UD の Siano firmware 診断もコードに明記されています。根拠: `proxy/bondriver/dvbv5.rs:171-174,229-241,251-278,556-580`。
- PX-W3U4 の4ノードは4個の物理チューナーとして各1登録します。番号から地デジ・衛星を推定せず、各ノードを実際にスキャンします。CharDev は全空間を列挙し、非対応空間の `EINVAL`、連続ロック失敗等でその空間を終了します。PX-S1UD×4 は各 frontend を1登録します。したがって提示された機器構成は合計8登録です。帯域ごとの6/2という台数は提示された実機情報であり、ノード番号との対応を自動推測した結果ではありません。根拠: 上記 backend と `proxy/scheduler/scan_scheduler.rs:596-673`。
- 新規登録は `max_instances=1`、`stream_format="ts"`、`disable_b25=false`、`scan_priority=0`、定期再スキャン無効、passive scan 無効、グループ未指定とします。グループは client-view で複数ドライバーをまとめる用途で、帯域指定ではありません。物理ノードを地デジ用・BS用の2件に分けると、path ごとの semaphore では物理排他が保証されません。1本で複数帯域を受けられる機器も1登録のまま使います。根拠: `proxy/web/api/bondrivers.rs:96-123,248-303`、`proxy/tuner/pool.rs:248-249,423-438,569-570`、`proxy/web/api/client_view.rs:65-115`。

登録リクエストの例:

```json
{
  "dll_path": "/dev/px4video0",
  "driver_name": "px4video0",
  "max_instances": 1,
  "stream_format": "ts",
  "disable_b25": false,
  "auto_scan_enabled": false,
  "scan_interval_hours": 24,
  "scan_priority": 0,
  "passive_scan_enabled": false
}
```

DVB は `dll_path` を `/dev/dvb/adapter0/frontend0` に置き換えます。名前・グループ・最大同時数等の既存設定は上書きしません。最大同時数が1以外なら警告し、スキャン前に修正を求めます。USB が消えた登録は警告して保持します。再列挙・故障・一時切断を区別できず、登録削除は局設定にも影響するためです。物理チューナーの識別に使うシリアル番号等は今回の API にありません。

スキャン順の `scan_priority=0` と、視聴・録画リクエストの優先度は別です。pool は SCAN=0 / VIEWING=10 / RECORDING_NORMAL=200 / RECORDING_EXCLUSIVE=255 を定義し、局選択priorityのDB既定値は0です。本セットアップはこれらの配信優先度や既存局priorityを変更しません。根拠: `proxy/tuner/pool.rs:81-87`、`proxy/database/schema.rs:17,58-59`。

## 2. 既存の検出・登録機構と選択理由

`recisdb-proxy-setup` は GUI ウィザードです。Linux の検出関数と登録関数があり、選択したデバイスを DB に登録して即時スキャンを予約します。ただし Dockerfile は proxy 本体だけを収録し、GUI は headless setup 用コマンドではありません。また検出パターンに実機の `px4video` がなく、登録ヘルパーは検出機種の合計台数を各 path の `max_instances` に設定する場合があります。この構成では Compose に実際に渡したノードを管理 API で登録する方が物理台数を正確に扱えます。

根拠: `recisdb-proxy/Cargo.toml:12-18`、`proxy/setup_helpers.rs:174-207,893-944`、`proxy/setup_gui.rs:817,1317-1338`、このリポジトリの `docker/recisdb-proxy/Dockerfile`。

通常起動は全 `/dev` を自動登録しません。`--tuner` または TOML `[server] tuner` から解決した単一 default tuner は登録でき、`--scan-on-start` でそのスキャンを予約できます。複数チューナーの `[[tuners]]` 設定をロードする仕組みは `ConfigFile` にはありません。根拠: `proxy/app_config.rs:28-51,186-193,336-339`、`proxy/main.rs:670-695`。

## 3. スキャン API と反映経路

1. `GET /api/bondrivers` で既存を取得し、未登録 path のみ `POST /api/bondriver` で登録します。
2. `GET /api/scan-history?bondriver_id=N` の最大履歴 ID を保存します。
3. `POST /api/bondriver/N/scan` で一度だけ予約します。既に `is_scanning=true` / `next_scan_at=0` なら現在の予約を待ちます。この POST は開始・完了を保証せず、DB の `next_scan_at=0` を設定するだけです。
4. `GET /api/bondriver/N` と履歴を既定5秒間隔で取得します。新しい履歴 ID・`success=true`・`channel_count>0`・スキャン終了・即時予約解消を確認します。過去の成功履歴で完了扱いにしません。細かいチャンネル進捗 API はありません。完了台数・経過秒と状態を行表示し、TUI では台数ゲージを併用します。
5. 全台成功後に Mirakurun channels/services が空でないことを確認します。EDCB を止める前に既存 `chset.py.generate()` で targets/ChSet を検証し、`scripts/edcb-chset.sh` で再取得・配置・再起動します。失敗時は既存 ChSet を保持し、setup 自体は警告後に続行します。
6. EPGStation と KonomiTV を再起動して更新を開始します。全処理成功時のみ `data/tuner-setup.json` に履歴ID・サービス一覧のハッシュ・EDCB利用有無を保存します。token は保存しません。

API と完了条件の根拠: `proxy/web/mod.rs:135-160`、`proxy/web/api/bondrivers.rs:20-38,420-486`、`proxy/database/bon_driver.rs:186-204,274-291`。

スキャンは DB の空間を限定条件にせず、backend が列挙した全空間を調べます。成功時は `merge_scan_results` で局を更新し履歴を書き、scheduler が `last_scan` と次回予約を更新します。Mirakurun はそのDBから有効かつ物理割当済みのサービスを重複排除して返すため、proxy の再起動は不要です。targets も同じ局DBを読んでドライバー別の有効チャンネル数を返し、ChSet API は client-view を生成します。根拠: `proxy/scheduler/scan_scheduler.rs:1281-1305,1348-1413,248-269`、`proxy/database/channel.rs:851-890,1005-1022`、`proxy/web/mirakurun.rs:704-715,785-810,875-950`、`proxy/web/api/client_view.rs:35-115,244-290`。

## 4. 時間・失敗・再実行

上流の既定値は scheduler確認60秒・同時1台・1台上限900秒・TS解析上限300000msです。録画や視聴で使用中なら次のtickへ延期します。本ツールは全台の物理割当を確認するため1台ずつ予約します。受信環境では1台数分・8台で数十分を見込む設計ですが、これは実測値ではありません。既定値だけから見た待機上限は1台1200秒、8台を全て上限近くまで待てば約160分です。最初の失敗で反映処理を中断します。根拠: `proxy/scheduler/scan_scheduler.rs:54-58,218-224,235-247`。

`--timeout` は1台の待機上限で、既定は `max(1200, scan_timeout_secs + 2*check_interval_secs + 120)`。`--poll` は照会間隔です。再実行時は自動登録を重複させません。`setup.sh` の `--automatic` 相当では最新履歴が受信局ありの成功なら再スキャンを省略し、反映成功記録も一致すればEDCBや他サービスも再起動しません。`make scan` は再スキャンを強制します。

上流の注意点:

- 全空間が空でも成功履歴になり得ます。0局をこちらで失敗扱いにします。さらに上流のmergeは見つからない既存局を無効化するため、アンテナ未接続で再スキャンするとproxy内の旧局は無効化され得ます。ChSetファイルは保持しますが、DBまでは復元しません。根拠: `proxy/scheduler/scan_scheduler.rs:1383-1413`、`proxy/database/channel.rs:1005-1022`。
- エラー・タイムアウト時は失敗履歴を書きますが `next_scan_at` を解消していません。予約は後のtickで再試行される場合があります。後続のscanを新たに積まず、原因修正と `make scan` の再実行を案内します。根拠: `proxy/scheduler/scan_scheduler.rs:271-288`、`proxy/database/bon_driver.rs:199-204`。
- クライアント側の待機タイムアウトはサーバーのスキャンをキャンセルしません。スキャンと通常配信が使う slot の競合は上流が扱いますが、利用者がAPI/Web画面から同時に別操作することまではローカルlockで防げません。

## 5. 認証と秘密情報

Web 認証はテンプレートで既定無効 (`[web] auth_enabled = false`)。アクセス元はファイアウォールで制限します。認証を有効にする場合は `true` と `auth_token` を設定します。既存設定の `true` は初回移行で false にし、`config/recisdb-proxy/backup/` へ退避します。明示された `auth_token` があれば認証設定を維持します。認証有効時、上流は OS CSPRNG の32バイトを64桁hexにし、`web_auth_config` の `id=1` の `auth_token` に保存します。TOML `[web] auth_token` があればそれを優先し、同じ値をDBにも保存します。ヘッダーは `Authorization: Bearer <token>`。Mirakurun 互換 API は認証不要です。根拠: `proxy/web/auth.rs:22-59,78-96`、`proxy/main.rs:487-530`、`proxy/database/mod.rs:2017-2037`。

本ツールは認証有効時だけホストの `data/recisdb/recisdb-proxy.db` を読み取り専用URIで開き、tokenをPython内だけに保持します。認証無効時はtokenなしでAPIへ接続します。curl引数や環境変数へ渡しません。管理API接続はホストのloopback HTTPに限定し、HTTP proxyとredirectを無効化します。APIのエラー本文、scan履歴のerror_message、Dockerの出力は秘密情報を反射し得るためそのまま出しません。DBディレクトリ0700、DB/WAL/SHMとTOML設定0600、proxy起動時umask077を使います。既存DBは実行ユーザーが所有するものだけ権限を補正します。所有UID不一致は起動・読み取り失敗として案内します。

tokenを含むINFOログは認証有効時に出る場合があります。通常の既定設定では認証無効のためtokenは生成・表示されません。認証を有効にする場合はログ保管先へのアクセスも制限してください。

## 6. EDCB・EPGStation・KonomiTV

EDCB の既存 ChSet generator を再利用し、Mirakurun サービス列挙番号へ変換した UTF-8 BOM 付き ChSet4/5 を配置します。EDCB 停止後に `.env` の `EDCB_TUNER_COUNT` と `[BonDriver_LinuxMirakc.so] Count` を公開中の実デバイス数へ同期し、他の設定を保持・変更前を退避します。停止中に異常が起きてもEDCBの再起動を試み、再起動失敗も呼び出し元へ返します。`[TVTEST] Num=1` はドライバー種類数なので変更しません。合計8というCountは地デジ6/衛星2の帯域別上限を表さず、同一帯域の過剰予約は別途実機で確認が必要です。

EPGStationのローカルフォークはイベントストリーム接続時に全件更新し、その中で局一覧も更新します。定期全件更新もあります。スキャン直後に局一覧更新を開始させるため再起動します。根拠: `/Users/ayumu/prog/EPGStation/src/model/epgUpdater/EPGUpdater.ts:104-134,152-170,209-221`、同 `EPGUpdateManageModel.ts:117-118,273-325`。

KonomiTV上流は起動時に Channel と Program を更新し、既定15分間隔でも更新します。この構成では再起動で直ちに更新を開始させます。起動時にはライブストリームオブジェクトも初期化されます。根拠: [tsukumijima/KonomiTV server/app/app.py:200-239](https://github.com/tsukumijima/KonomiTV/blob/master/server/app/app.py#L200-L239)。実際にビルドするフォークでも `/Users/ayumu/prog/KonomiTV/server/app/app.py:229-260` の同等処理を確認しました。

proxy のEPG取得はチャンネルスキャンと別のschedulerです。既定有効、評価間隔300秒で局DBから対象を選びます。再起動や設定上書きは不要です。既にEPG取得を無効化した環境の選択は変更しません。根拠: `proxy/database/epg_settings.rs:18-27`、`proxy/scheduler/epg_scheduler.rs:320-347`。EDCBの番組表はChSet配置だけでコピーされず、既存のEPG定期取得時刻またはWebUIのEPG取得で埋まります。既定設定には06:00/18:00があるため、局認識直後にEDCB番組表が空でもChSet失敗とは限りません。

## 7. 上流に必要・望ましい改修

今回の正常系自動化に必須のAPI追加はありません。以下は上流へ実装せず、制約として残しました。

1. token平文ログの削除、または専用の安全な取得経路。
2. スキャンjob ID・チャンネル進捗・キャンセルAPI。現状は履歴と状態で待ちます。
3. 失敗/timeout時の予約クリアまたはバックオフ。失敗チューナーの再試行が他台の処理を妨げる可能性があります。
4. 全0局/部分失敗時に既存局を無効化する前の保護、明確な失敗結果。
5. GUI検出の `px4video` 対応と、Linux物理ノードごとのmax_instances=1。今回GUIを使わないため回避済みです。
6. DVBでのISDB-S対応が必要ならbackend改修。今回のPX-S1UDは地デジのみなので不要です。

## 8. 実機での確認手順

録画・視聴がない時間に、`docker compose build recisdb-proxy edcb` で更新したイメージをビルドして起動し、`make tuners && make scan` を実行してください。`make tuners` はデバイス変更によりproxyを再作成する場合があります。

- 8登録、各max_instances=1、重複なし。DVBは4 frontend、PX-W3U4は4ノード。消失USBは削除せず警告。
- 各履歴の成功・受信局数、GR/BS/CSの実受信内訳。S1UDのfirmware、video GID、DVB frontend/demux書込権限。
- Mirakurun channels/services、targets、有効局数の一致。地デジ/衛星の同時受信とLNB給電。
- EDCB ChSet4/5とバックアップ、Count=8、Num=1、予約保持、WebUI局一覧。帯域別同時録画上限。
- EPGStation/KonomiTVの局一覧・番組表更新、proxyのEPG取得継続。EDCBは次のEPG取得後の番組表。
- 2回目の `./setup.sh --yes --no-build` が再スキャン・サービス再起動を省略すること。`make scan` は再実行すること。
- アンテナ未接続時の警告とsetup続行、タイムアウト時のサーバー側継続表示。旧ChSet保持とproxy内の局無効化の違い。
- 認証有効時のtoken保護、DB/TOML権限、起動後のstdout・ディスクログを確認。認証無効時はtokenなしで動くことを確認。
- B25復号、予約録画、再生。テストの成功は実受信成功の代わりにはなりません。


## 9. 検証結果

調査時点の指定5コマンドは終了コード0でした。今回の認証既定値変更後の結果は再検証が必要です。

Docker 上の実行、実受信、実録画は実機で確認する。
