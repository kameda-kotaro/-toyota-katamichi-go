# トヨタ「片道GO!」→ Discord 新着通知

トヨタレンタカーの「片道GO!」ページを30分ごとに確認し、前回にはなかった掲載をDiscordへ通知します。

## 仕組み

1. GitHub Actionsが30分ごとに公式ページを取得
2. 掲載一覧を抽出
3. 前回の一覧 (`state.json`) と比較
4. 新しい掲載だけDiscord Webhookへ送信
5. 現在の一覧を `state.json` に保存して自動コミット

初回実行時は現在の掲載を「既知」として登録し、Discordには監視開始メッセージだけを送ります。現在掲載中の案件を大量通知することはありません。

## セットアップ

### 1. GitHubにリポジトリを作る

GitHubで新しいリポジトリを作成し、このフォルダの中身をそのままアップロードします。

費用を確実に0円にしたいなら、**Public（公開）リポジトリ**が分かりやすいです。標準のGitHub-hosted runnerはPublicリポジトリで無料です。Webhook URL自体はGitHub Secretsに入れるため、コードには公開されません。

Private（非公開）でもGitHub FreeにはActionsの無料枠がありますが、実行時間を消費します。このテンプレートは30分間隔にしてあります。

### 2. DiscordでWebhookを作る

通知したいDiscordチャンネルを開きます。

- チャンネル設定
- 連携サービス
- ウェブフック
- 新しいウェブフック
- Webhook URLをコピー

Webhook URLは他人に見せないでください。

### 3. GitHub SecretにWebhook URLを登録

GitHubリポジトリで次を開きます。

`Settings` → `Secrets and variables` → `Actions` → `Secrets` → `New repository secret`

- Name: `DISCORD_WEBHOOK_URL`
- Secret: DiscordでコピーしたWebhook URL

### 4. Actionsを手動で1回実行

GitHub上部の `Actions` → `Toyota Katamichi GO Monitor` → `Run workflow` を押します。

成功するとDiscordに「監視を開始しました」と届きます。以降は30分ごとに自動確認されます。

## 経路・車種を絞り込みたい場合（任意）

GitHubの

`Settings` → `Secrets and variables` → `Actions` → `Variables`

に以下を追加できます。

| Variable | 例 | 意味 |
|---|---|---|
| `FILTER_START` | `東京,神奈川` | 出発店舗に東京 **または** 神奈川を含むもの |
| `FILTER_RETURN` | `大阪,京都` | 返却店舗に大阪 **または** 京都を含むもの |
| `FILTER_CAR` | `アルファード,ハイエース` | 車種にどちらかを含むもの |

各項目内はカンマ区切りでOR検索、異なる項目どうしはAND条件です。

例:

- `FILTER_START = 東京,神奈川`
- `FILTER_RETURN = 大阪`

なら「東京または神奈川から出発し、大阪へ返却する掲載」だけ通知します。

何も設定しなければ全国・全車種が通知対象です。

## 実行間隔を変える

`.github/workflows/monitor.yml` の以下を変更します。

```yaml
- cron: "*/30 * * * *"
```

30分ごとならそのままでOKです。

## 注意

- 公式サイトのHTML構造が大きく変更されると、解析部分の修正が必要になることがあります。
- GitHub Actionsの定刻実行は混雑時に多少遅れることがあります。
- Discord Webhook URLはコードに直接書かず、必ずGitHub Secretsに保存してください。
