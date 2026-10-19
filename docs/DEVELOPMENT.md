# 開発・検証記録

### この変更の検証範囲

Mac 上の検証対象は shellcheck、bash 構文検査、`make test`、Compose YAML 読み込み、Compose CLI の実際の `config` による 128 通り (BonCasRelay × EDCB × Amatsukaze × HTTPS × GPU 4 種 × KFD 有無。AMD 以外は KFD 有無による差分なし) の構成です。`tests/compose_test.py` は `COMPOSE_BIN=/path/to/docker-compose python3 tests/compose_test.py` で再実行できます。

設定ファイルの初回生成・再生成・移行・バックアップと復元は `tests/config_test.py` と `tests/setup_test.sh` で、Docker をスタブに置き換えて検証しています。実際のコンテナ起動による確認は含みません。

生成した EPGStation config.yml はローカルフォークの実物の `IConfigFile.ts` に対して TypeScript の `Partial<IConfigFile>` で型照合し、`ConfigSchema.ts` の DB キーも確認しました。EDCB、Lua 5.2、両候補の BonDriver は x86_64 Linux ELF にクロスビルドしました。クロス環境では CC/CXX/LD/OBJCOPY を Linux 向けに指定し、古い sysroot 用に `-ldl -lrt` を明示しました。Dockerfile は noble の glibc と Ubuntu 配布 Lua を使うため、このクロス環境向け補助指定は不要です。

（記述時点）この Mac には Docker daemon がないため、Ubuntu 24.04 イメージ全体のビルド・起動、MariaDB 実接続、EDCB WebUI の実応答、EPG 取得、実録画・復号・KonomiTV との同時利用、Akebi 経路は未検証です。Linux 録画ホストでこれらを確認してください。
