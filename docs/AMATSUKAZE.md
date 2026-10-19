# Amatsukaze

## 録画を自動で CM カット・エンコードする (Amatsukaze)

`./setup.sh` の初回質問「Amatsukaze を使いますか」は既定ではいです。初回選択後は `SETUP_AMATSUKAZE` に保存した有効・無効を再設定時の既定として保ちます。非対話では `AMATSUKAZE=yes ./setup.sh --yes`、無効にする場合は `AMATSUKAZE=no ./setup.sh --yes` と指定します。設定だけ変更する場合は `--reconfigure` を付け、後から `make build && make up` で反映します。既存 `.env` の誤った `EPGSTATION_REF=master` は `main` に移行します。カスタム ref は維持します。

Amatsukaze は `COMPOSE_FILE` に `compose.amatsukaze.yaml` を追加したときだけ起動します。手動構成では `AMATSUKAZE_VERSION=1.1.1.2`、`AMATSUKAZE_WEBUI_PORT=32769`、`RUN_UID` / `RUN_GID` を設定してください。UID/GID は `id -u` / `id -g` と録画先の所有者に合わせます。有効時は EPGStation と Amatsukaze が同じ UID/GID で実行されます。EPGStation は既存のアプリ設定・DB・ログ・サムネイル・drop の所有者を起動時に整えますが、既存録画の所有者は変更しません。以前 root で録画したファイルや `/recorded/tmp` がある場合は、対象の権限を管理者が確認してください。無効時の EPGStation 実行ユーザーは従来どおりです。

1. `http://<録画ホストIP>:32769/` を開きます。初回起動で `EPGStation` プロファイルが自動作成されます。既に同名プロファイルがある場合は上書きしません。
2. WebUI で各放送局のロゴデータを登録し、サービス設定で対象局とロゴを対応付けます。対象局の「CM 解析無効」を解除し、JoinLogoScp コマンド (通常 `JL_標準.txt`) を確認します。プロファイルだけでは局別設定を代行できません。ロゴ未登録のジョブは待機・失敗するため、最初は短い実録画で確認してください。
3. EPGStation の録画画面からエンコードを実行し、設定一覧の **Amatsukaze** を選びます。接続先やエンコードコマンドの手編集は不要です。
4. 自動化する場合は EPGStation の自動予約ルールを開き、録画後エンコード設定に **Amatsukaze** を選んで保存します。まず TS の自動削除は無効のまま、CM 境界・ロゴ消し・音声・完了結果の再生を確認します。

`EPGStation` プロファイルは上流 `defaults/profile/デフォルト.profile` の XML を基に、名前を `EPGStation`、`DisableChapter=false`、`OutputMask=2` (CM カット) に変更したものです。`EncoderType=x264`、MP4、`NoDelogo=false` (ロゴ消し有効)、CUDA 無効、入力移動・リネーム無効です。字幕は上流既定どおり無効です。局別ロゴと CM 解析設定は必要です。WebUI で品質やインターレース解除、字幕を調整してください。

setup.sh はイメージビルド後に実エンコードを試し、未編集の `EPGStation` プロファイルを QSVEnc / NVEnc / VCEEnc / x264 に設定します。Intel は `compose.intel.yaml` と `compose.amatsukaze.intel.yaml`、AMD は `compose.amd.yaml` と `compose.amatsukaze.amd.yaml`、NVIDIA は `compose.nvidia.yaml` と `compose.amatsukaze.nvidia.yaml` を選びます。専用ファイルは Amatsukaze 有効時だけ追加します。手動編集済みファイルは上書きしません。プローブ結果とバックアップ、手動反映手順は [GPU 設定ガイド](GPU.md) を参照してください。

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
| GPU が使われない | GPU override、ホストのドライバーと Toolkit、`config/gpu-probe-log.json` と手動編集保護によるスキップを確認 |

根拠: [ProfileSetting と出力マスク](https://github.com/rigaya/Amatsukaze/blob/1.1.1.2/AmatsukazeServer/Server/EncodeServerData.cs)、[局別 CM 解析・ロゴ消しの適用](https://github.com/rigaya/Amatsukaze/blob/1.1.1.2/AmatsukazeServer/Server/TranscodeWorker.cs)、[上流既定プロファイル](https://github.com/rigaya/Amatsukaze/blob/1.1.1.2/defaults/profile/デフォルト.profile)、[Linux インストール](https://github.com/rigaya/Amatsukaze/blob/1.1.1.2/doc/InstallLinux.md)、[EPGStation 連携コマンド](https://github.com/stuayu/EPGStation/blob/main/src/AmatsukazeEncodeTool.ts)、[パス変換](https://github.com/stuayu/EPGStation/blob/main/src/model/amatsukaze/AmatsukazeConfigResolver.ts)。
