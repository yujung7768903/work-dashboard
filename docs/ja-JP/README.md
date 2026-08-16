# ワークダッシュボード

[English](../../README.md) · [한국어](../ko-KR/README.md) · **日本語** · [中文](../zh-CN/README.md)

Claude Code と一緒に作業する人のためのローカル作業管理ツール。人はブラウザから、
Claude は CLI から操作し、両者が同じ SQLite ファイルを読み書きする。フレームワークも
バンドラーも `pip install` も不要。

作業は **カテゴリ → ワークスペース → タスク** の 3 階層で管理する。その上で Claude Code
のセッションが一つずつ登録され、ワークスペースに分類され、実際に着手しているタスクへ
リンクされる。だからボードには常に何が動いているかが映り、次のセッションは状況を
把握した状態で始められる。

> [!NOTE]
> 1 人用で認証はなく、外部サービスも使わない。すべては自分のマシン上の SQLite
> ファイル 1 つに収まっている。

## 特徴

- **3 階層ボード** — カテゴリがワークスペースをまとめ、ワークスペースがタスクを持つ。
  優先度は並び順だけで表し、すべてドラッグで並べ替えられる。
- **セッションのリアルタイム追跡** — フックが Claude Code のセッションを登録し、
  ワークスペースのコンテキストを注入し、作業中もボードを同期し続ける。
- **ワークツリー管理** — 各 git ワークツリーの状態とコミットを確認し、その開発サーバーを
  ボードから直接 起動・再起動・停止できる。
- **マージはワンコマンド** — 状態確認 → 対象ブランチの取り込み → テスト → マージ →
  タスク・サーバー・ブランチの解放、をこの順に行う。
- **自律実行** — ラベルの付いたタスク 1 件を 5 分間隔の cron でバックグラウンドの
  `claude` ジョブに任せる。既定はオフ。
- **使用量ビュー** — ローカルの Claude Code ログから読んだ利用上限ウィンドウと、
  日次のトークン・コスト推移。
- **ステータスライン** — 現在のタスク・ワークツリー・サーバーポートを Claude Code の
  ステータスラインに描画する。
- **UI 言語 4 種** — 英語(既定)・韓国語・日本語・中国語。地球アイコンから切り替える。
  サーバーが返す文言も選んだ言語に従う。
- **ライト・ダーク** — 太陽と月のアイコンから、端末の設定 / ライト / ダークを選ぶ。
  アカウントではなくブラウザごとに残る。

## 必要なもの

| | |
| --- | --- |
| 必須 | Python 3.9+(標準ライブラリのみ)、Git、モダンブラウザ |
| 任意 | Claude Code — セッション追跡・ステータスライン・自律実行に必要 |
| 任意 | Node.js — テストの一部の画面チェックが `node` で動く |
| 任意 | `PATH` 上の `markdownlint-cli2` — Markdown lint フックが使う |

## クイックスタート

```bash
git clone https://github.com/yujung7768903/work-dashboard.git
cd work-dashboard
./start.sh
```

そして `http://127.0.0.1:9080` を開く。DB は初回接続時に作られるので、マイグレーションや
セットアップの手順はない。

```bash
./start.sh --port 9081     # 別のポート。たとえばワークツリー用
./start.sh --lan           # スマホやタブレットからも開けるように
./restart.sh               # このディレクトリから起動したサーバーを再起動
./stop.sh                  # 停止
./stop.sh --port 9081      # そのポートで動いているものだけ
python3 server.py          # フォアグラウンドで実行
```

`start.sh` は引数をそのまま `server.py` に渡し、pid とログのパスを表示する。ログは
1 日 1 ファイル(`logs/YYYY-MM-DD.log`)で、7 日以上触れられていないファイルは次回起動時に
削除される。

`stop.sh` と `restart.sh` は、このディレクトリを作業ディレクトリとするサーバーだけを
対象にする。ワークツリーのサーバーとメインチェックアウトのサーバーが互いを止めることは
ない。1 つのディレクトリで複数動いているときは `--port` で対象を絞る。

`--lan` は `start.sh` 自身が解釈する唯一のフラグで、`0.0.0.0` にバインドしたうえで、
他の端末にそのまま貼り付けられるアドレス(`http://192.168.x.x:9080`)を表示する —
`server.py` がそのまま返す `0.0.0.0` ではなく。

> [!WARNING]
> `--lan` を付けると、同じネットワーク上の誰でもダッシュボードを開ける。認証はない。

9080 はメインチェックアウトの席だ。常に同じアドレスであるためで、ワークツリーは 9081
から使う。ワークツリー内で起動した `server.py` は `--port 9080` を拒否する。

## Web 画面

| タブ | 内容 |
| --- | --- |
| ボード | ツリー全体、次にやるタスク、実行中セッション(2 秒ポーリング)、自律実行スイッチ |
| ワークスペース | ワークスペースの作成と、背景・目的・ゴール・考慮事項の編集 |
| 設定 | カテゴリとラベル |
| 使用量 | 利用上限ウィンドウとトークン・コスト推移 |

ボードにはサブタブが 2 つある — **タスク** と **ワークツリー**。ワークツリーのサブタブ
では、各行のケバブメニュー(⋮)からそのワークツリーを適用(マージ)・削除し、サーバーを
起動・再起動・停止する。このサブタブはワークスペース別・プロジェクト別にまとめて表示で
き、プロジェクト別ビューではどのワークスペースにも紐づかないワークツリーも並ぶ。どちら
のサブタブもカードを 1 列・2 列に切り替えられ、左のレールはアイコンだけに畳める。

タスクの行とセッションの行は同じダイアログを開き、ダイアログはタブ 3 つで構成される。

| ダイアログのタブ | 内容 |
| --- | --- |
| 概要 | タイトル、履歴、着手条件、コンテキストノート全文 |
| セッション | セッション id・場所・直近 10 件のやり取り、ワークスペース/カテゴリの指定 |
| ワークツリー | そのタスクが使ったワークツリー — 状態・履歴・コミット |

## CLI

`dash.py` は Claude Code が使うエントリポイント。すべてのコマンドが Web と同じ DB を
見るので、片方の変更はもう片方で再読み込みすれば反映される。

### ボード

```bash
python3 dash.py ls                                   # ツリー全体
python3 dash.py next                                 # 次にやるタスク 1 件
python3 dash.py show <ワークスペースid|JIRA-1>         # ワークスペース詳細
python3 dash.py add-category <名前>
python3 dash.py add-workspace <カテゴリ> <名前> [--background ...] [--jira KEY]
python3 dash.py add-todo <タイトル> [--workspace ID] [--note ...] [--precondition ...]
python3 dash.py move-todo <タスクid> --workspace <id|none>
python3 dash.py set-status <todo|workspace> <id> <状態>
python3 dash.py reorder <categories|workspaces|todos> <ids...>
python3 dash.py done-today [--date YYYY-MM-DD]
```

### セッション

```bash
python3 dash.py sessions                             # 実行中のセッション
python3 dash.py classify --category <名前> [--workspace <id>]
python3 dash.py link-todo <タスクid> [--status done] [--past]
python3 dash.py show-todo --session
python3 dash.py show-note <タスクid>                  # コンテキストノート全文
```

`link-todo` は、このセッションがそのタスクに着手したという宣言であり、タスクを `doing`
に進める。実際に取り組んでいるものだけを紐づける — `merge` はセッションに紐づいた
タスクをすべて閉じるので、後回しのために作った後続タスクは、実際に着手するセッションが
紐づけるまで紐づけない。`--past` は終わった履歴セッションを紐づけ、状態は変えない。

セッション引数は省略できる。省略すると、Claude Code がセッションの起動する全プロセスに
渡す `CLAUDE_CODE_SESSION_ID` から自分のセッションを特定する。

### ワークツリーとマージ

```bash
python3 dash.py merge                        # 確認 → 対象の取り込み → テスト → マージ → 解放
python3 dash.py merge --message "タイトル"    # マージコミットのタイトル
python3 dash.py merge --test "npm test"      # tests/__main__.py がないリポジトリ
python3 dash.py merge --no-test
python3 dash.py finish [--worktree PATH]     # 解放のみ — タスクを done、サーバーを停止
python3 dash.py statusline <セッション> [--cwd PATH]
```

`merge` は対象ブランチをワークツリーへ取り込んだ後にテストを **1 回だけ** 走らせる。
テストしたツリーがそのままマージされるツリーになる。コンフリクトで止まったら、ファイルを
解決して `git add` し、同じコマンドをもう一度実行すれば続きから進む。push はせず、
ワークツリーの削除もしない — それは `ExitWorktree` の役目。

### 初期設定・言語・自律実行

```bash
python3 dash.py onboard [--skip]             # 初期設定がまだ必要な状態か
python3 dash.py scan-history --days 7        # 過去セッションごとに 1 行の要約
python3 dash.py language [en|ko|ja|zh]       # 引数なしなら現在の値
python3 dash.py usage                        # 利用上限とトークン推移
python3 dash.py autorun on|off|status
python3 dash.py autorun-tick [--dry-run]     # 5 分 cron が呼ぶエントリポイント
python3 dash.py autorun-prompt <タスクid>     # 自律セッションに入る指示の全文
python3 dash.py autorun-request "<理由>"      # 判断を保留し、人に決定を求める
python3 dash.py autorun-finish               # 完了 — レビュー待ちへ
```

## Claude Code 連携

### セッションコンテキスト

フックはセッションごとに `<work-dashboard state="...">` ブロックを **1 つだけ** 注入する。
どれが入るかはボードの状態で決まる。

| 状態 | 条件 | 注入される内容 |
| --- | --- | --- |
| `classified` | ブランチの Jira ID で一致したか、`classify --workspace` で紐づいたワークスペースがある | 背景・目的・ゴール・考慮事項、タスク一覧、スコープ遵守の指針 |
| `onboarding` | ワークスペースが 1 つもなく、ユーザーが拒否もしていない | 初期設定の手順 |
| `unclassified` | それ以外 | 現在地・ブランチ、カテゴリ、進行中ワークスペース、分類手順 |
| `released` | このセッションが取ったタスクがすべて `done` | 新しい依頼は終わったタスクに乗せず、新しいタスクとして受けるよう指示 |

分類そのものは自動ではない — シェルには質問が何についてのものか分からない。フックは指示を
注入するだけで、Claude が `classify` と `link-todo` で登録する。

### フック

すべてのフックは、どんな失敗でも黙って `exit 0` で終わる。ダッシュボードの不調で
セッションが開けなくなったり、ファイルを編集できなくなったりしてはならない。`exit 2` は
ブロックすること自体が目的の場合にだけ使う。

| フック | イベント | 役割 |
| --- | --- | --- |
| `hooks/dash_hook.py` | `SessionStart`・`UserPromptSubmit`・`Stop`・`SessionEnd` | セッションの登録と状態追跡、上記コンテキストブロックの注入 |
| `hooks/worktree_serve.py` | `Stop` | 変更したワークツリーを提供するサーバーがなければブロックし、空きポート(9081–9139)を渡す |
| `hooks/worktree_guard.py` | `PreToolUse`(`Write`・`Edit`・`NotebookEdit`) | `~/work/` のメインチェックアウトでのソース編集をブロック。`ALLOW_MAIN_CHECKOUT=1` で回避 |
| `hooks/commit_scope_guard.py` | `PreToolUse`(`Bash`) | pathspec のない `git add -A`・`git commit -a` をブロック。`ALLOW_BROAD_COMMIT=1` で回避 |
| `hooks/md_lint.py` | `PostToolUse`(`Write`・`Edit`・`NotebookEdit`) | このリポジトリに保存された `.md` を `markdownlint-cli2` で検査 |
| `hooks/stale_base.py` | `UserPromptSubmit` | ブランチが upstream や基準ブランチより遅れていればセッションにつき 1 回警告 |

`worktree_serve.py` はこのリポジトリの `.claude/settings.json` に登録済みなので、clone
した直後でも設定は不要。残る 5 つは `~/.claude/settings.json` に絶対パスで登録する。
パスはワークツリーではなくメインチェックアウトを指す必要がある — ワークツリーはマージ後に
削除されるからだ。

```json
{
  "hooks": [
    {
      "type": "command",
      "command": "python3 /絶対パス/work-dashboard/hooks/dash_hook.py SessionStart",
      "timeout": 2
    }
  ]
}
```

`dash_hook.py` はイベント名を唯一の引数として受け取るので、最後の引数だけを変えて
イベントごとに 1 つずつ追加する。

### ステータスライン

`~/.claude/statusline-command.js` が `dash.py statusline <セッション> --cwd <パス>` を呼び、
その出力を使用率バーの下の 2 行目に描く。

```text
Context ████░░░░░░ 42% │ Usage ███░░░░░░░ 30% │ Weekly ██████░░░░ 55%
[doing | tab-underline | :9092] ボードのタスクとワークツリーをサブタブに分割
```

角かっこの中は常に **状態 | ワークツリー | ポート** の順で、欠けている項目は区切りごと
消える。3 つとも無ければ角かっこ自体が出ない。

### 自律実行

`autorun on` にすると、5 分間隔の cron がタスクを 1 件選び、バックグラウンドの `claude`
ジョブとして実行する。対象は `auto` ラベルの付いたタスクだけ — 自律実行の許可は人が
与えるものであって、コードが推測するものではない。既定はオフで、自動的に再びオンになる
経路はない。

```cron
*/5 * * * * /usr/bin/python3 /絶対パス/work-dashboard/dash.py autorun-tick >/dev/null 2>&1
```

対象がない tick は何もしない。デーモンではなく cron にしている理由がこれだ。

## 設定

| 項目 | 場所 |
| --- | --- |
| DB | `~/.claude/work-dashboard/dash.db`。`WORK_DASHBOARD_DB` で上書き |
| ホスト・ポート | `server.py --host` / `--port`(既定 `127.0.0.1:9080`) |
| UI 言語 | 地球アイコン、または `dash.py language`。`meta.language` に保存 |
| 表示の好み | 明るさ・ボードの列数・レールの畳み — ブラウザの `localStorage` に保存 |
| UI 文言 | `static/lang/{en,ko,ja,zh}.json`。キーは共通で、英語がフォールバック |
| デザイントークン | `static/css/app.css` の `:root` — 余白・文字・角丸の唯一の出典 |
| Markdown ルール | `.markdownlint.json` |

## データモデル

SQLite を Web サーバー・CLI・フックが直接開く。仲介するプロセスはない。`connect()` が
スキーマを作り、外部キーと WAL を有効にし、既定カテゴリ 6 件を初回だけ投入する。
`*_at` 列はすべて ISO 8601 UTC のテキスト。

| テーブル | 役割 |
| --- | --- |
| `categories` | 最上位のグルーピング。優先度には関与しない |
| `workspaces` | ブランチや Jira 単位の作業。背景・目的・ゴール・考慮事項を保持 |
| `todos` | タスク。ワークスペースに属することも、カテゴリ直下に置くこともできる |
| `labels`・`todo_labels` | ラベルはタスクの性質なので、1 件に複数付く |
| `sessions` | Claude Code のセッション。フックが登録・更新する |
| `session_todos` | セッションが取ったタスク。セッションのワークスペースはここから導かれる |
| `worktrees` | ワークツリーの履歴。マージや削除でディレクトリが消えても残る |
| `usage_samples` | 使用量ビューが使う上限・トークンのサンプル |
| `autorun_state`・`autorun_runs` | 自律実行の設定と実行記録 |
| `meta` | 単一値の設定と内部フラグ |

## プロジェクト構成

```text
work-dashboard/
├── dash.py               # CLI エントリポイント — 解析・委譲・出力のみ
├── server.py             # HTTP エントリポイント(http.server、フレームワークなし)
├── start.sh              # バックグラウンド起動、日付別ログ、7 日で整理
├── stop.sh · restart.sh  # このディレクトリのサーバーだけを扱う
├── serving.sh            # サーバー検出・停止の共通関数
├── app/
│   ├── constants.py      # マジックナンバーはすべてここへ
│   ├── db.py             # 接続・スキーマ・トランザクション
│   ├── repositories/     # エンティティ別の保存・取得と整合性ルール
│   └── services/         # 複数エンティティにまたがるロジック
├── hooks/                # Claude Code フック
├── static/               # ES モジュールのフロントエンド(バンドラーなし)
│   ├── index.html        # 単一ページ。文言は持たず data-i18n キーだけを持つ
│   ├── lang/             # en · ko · ja · zh、キー集合は同一
│   ├── css/              # app.css がトークンを定義し、usage.css は参照のみ
│   └── js/               # boot・i18n・theme・layout・board・workspace・sessions・usage
├── tests/                # python3 -m tests
└── docs/superpowers/     # 設計ドキュメントと計画
```

## テスト

```bash
python3 -m tests
```

リポジトリ・サービス・CLI・フックを対象にし、4 つの言語ファイルでキーとプレースホルダーが
一致することを確認し、CSS の余白と文字が生の px ではなくデザイントークンを使うことを
強制する。画面の挙動チェックは `node` で動き、同名の Python テストが呼び出す。`start.sh`
などのスクリプトを実際に実行するテストは 9900–9999 番でサーバーを起動し、この帯域は
画面には描かれない。

## 設計ドキュメント

`docs/superpowers/specs/` に段階ごとの設計と確定した決定が、`docs/superpowers/plans/` に
実装計画が置かれている。
