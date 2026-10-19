# BonCasRelay とカードリーダー

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

## BonCasRelay を同じマシンで動かす

local を選ぶと `compose.boncasrelay.yaml` を追加し、公開ソースから `cargo build --locked --release --no-default-features -p boncasrelay` でビルドします。`BONCASRELAY_REPO` / `BONCASRELAY_REF` で取得元を指定できます。PC/SC はコンテナ内の `pcscd`・`libpcsclite1`・`libccid` を使います。[BonCasRelay README と INI 例](https://github.com/stuayu/BonCasRelay#設定)に従い、`[General] ServerPort=6900` / `Allow`、`[Web] Listen` / `Enabled` を生成します。

カード通信はホストへ公開せず、recisdb-proxy の B25/4K 接続先はどちらも `boncasrelay:6900` です。WebUI はコンテナ内 `0.0.0.0:6980`、ホストでは `127.0.0.1:6980:6980` のみ公開します。UFW の 6900 許可ルールは同梱構成では不要です。別マシンの Relay を使う場合は、カードホスト側で録画ホスト IP からの 6900 を許可します。

`Allow=@compose-subnets@` を起動時にコンテナの接続済み IPv4 サブネットへ展開し、`/run/boncasrelay.ini` を生成します。Compose default network の IPAM は変更しません。複数サブネットには上流の INI 仕様に従って `Allow` を複数行出力します。以前の既定値 `Allow=172.30.69.0/24` も起動時に展開し、独自に指定した ACL は維持します。recisdb-proxy の既存 TOML を local に切り替える場合は `make regen-config SERVICE=recisdb-proxy` も必要です。

USB は `/dev/bus/usb` 全体をバインドし、`device_cgroup_rules: ['c 189:* rw']` で USB device major 189 の全 minor に読み書きを許可します。固定の `devices:` では再接続後のノード番号変更に対応できないため、この方式を採用しています。`privileged`・ホストの PC/SC socket・ホストネットワークは使いません。ただしコンテナから全 USB デバイスにアクセスできる点は把握してください。根拠は [Linux device 番号表](https://docs.kernel.org/admin-guide/devices.html)と [Compose device_cgroup_rules](https://docs.docker.com/reference/compose-file/services/#device_cgroup_rules) です。

さらに sysfs の CCID インターフェース (`bInterfaceClass=0x0b`) に対応する busnum/devnum の集合を 2 秒ごとに確認し、リーダーの増減・再列挙があればコンテナを終了して `restart: unless-stopped` で pcscd と Relay を起動し直します。[pcsc-lite の udev 実装](https://github.com/LudovicRousseau/PCSC/blob/1.9.9/src/hotplug_libudev.c)はイベントを監視しますが、コンテナ内へのホストイベント通知を前提にせず、再起動時の列挙で回復させます。無関係な USB 機器やチューナーの接続変更では再起動しません。`/dev/bus/usb` がなければ警告して監視を無効化し、サービスを起動します。`pcscd --hotplug` は非 USB リーダー用、`--force-reader-polling` は IFD の通知能力を無視する指定で、udev の USB 再検出ポーリングを有効にするものではありません ([Ubuntu noble の manpage](https://manpages.ubuntu.com/manpages/noble/en/man8/pcscd.8.html))。配布版 pcscd の udev 実装を継続利用し、CCID が変化した場合にだけ再起動して回復します。USB 抜き差し後の実際の再接続・復号は Linux 実機で確認してください。

ホストの `pcscd.service` または `pcscd.socket` が有効な場合は、両方の停止・無効化を表示して確認します。別アプリでもカードリーダーを使っている場合は、影響を確認してから選択してください。設定は `config/boncasrelay/boncasrelay.ini`、ログは `docker compose logs boncasrelay` です。
