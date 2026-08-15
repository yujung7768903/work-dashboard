# 工作看板

[English](../../README.md) · [한국어](../ko-KR/README.md) · [日本語](../ja-JP/README.md) · **中文**

一个面向「与 Claude Code 搭档工作」的本地任务管理工具。人从浏览器操作，Claude 从 CLI
操作，两边读写同一个 SQLite 文件。没有框架，没有打包器，也不需要 `pip install`。

工作按 **分类 → 工作区 → 待办** 三层组织。在此之上，每个 Claude Code 会话都会被注册、
归入某个工作区，并关联到它实际正在处理的待办。因此看板始终显示当前在跑什么，下一个会话
也能在了解进度的前提下开始。

> [!NOTE]
> 单人使用，无鉴权，不依赖任何外部服务。所有数据都在本机的一个 SQLite 文件里。

## 功能

- **三层看板** —— 分类归拢工作区，工作区容纳待办。优先级只用顺序表达，且全部支持拖拽
  排序。
- **会话实时追踪** —— 钩子注册每个 Claude Code 会话，注入其工作区上下文，并在工作过程中
  持续同步看板。
- **工作树管理** —— 查看每个 git 工作树的状态与提交，并直接从看板启动、重启或停止它的
  开发服务器。
- **一条命令完成合并** —— 状态检查 → 拉入目标分支 → 跑测试 → 合并 → 释放待办、服务器与
  分支，严格按此顺序。
- **自主执行** —— 把带标签的一条待办交给五分钟 cron 拉起的后台 `claude` 任务。默认关闭。
- **用量视图** —— 从本地 Claude Code 日志读取的限额窗口，以及每日 token 与费用趋势。
- **状态栏** —— 把当前待办、工作树和服务器端口渲染进 Claude Code 状态栏。
- **四种界面语言** —— 英语(默认)、韩语、日语、中文，点击地球图标切换。

## 环境要求

| | |
| --- | --- |
| 必需 | Python 3.9+(仅标准库)、Git、现代浏览器 |
| 可选 | Claude Code —— 会话追踪、状态栏与自主执行需要 |
| 可选 | Node.js —— 测试中的部分界面检查在 `node` 下运行 |
| 可选 | `PATH` 中的 `markdownlint-cli2` —— Markdown lint 钩子会用到 |

## 快速开始

```bash
git clone https://github.com/yujung7768903/work-dashboard.git
cd work-dashboard
./start.sh
```

然后打开 `http://127.0.0.1:9080`。数据库在首次连接时创建，因此没有迁移或初始化步骤。

```bash
./start.sh --port 9081     # 换个端口，例如给工作树用
./restart.sh               # 重启由本目录启动的服务器
./stop.sh                  # 停止
python3 server.py          # 改为前台运行
```

`start.sh` 会把参数原样传给 `server.py`，并打印 pid 和日志路径。日志按天一个文件
(`logs/YYYY-MM-DD.log`)，超过七天未被写入的文件会在下次启动时清理。

`stop.sh` 与 `restart.sh` 只作用于以本目录为工作目录的服务器，因此工作树的服务器和主
检出的服务器不会互相误杀。

> [!WARNING]
> `python3 server.py --host 0.0.0.0` 会把看板暴露到局域网，而且没有任何鉴权。

## 网页界面

| 标签页 | 内容 |
| --- | --- |
| 看板 | 完整树、下一件待办、正在运行的会话(每 2 秒轮询)、自主执行开关 |
| 工作区 | 创建工作区，编辑背景、目的、目标与注意事项 |
| 设置 | 分类与标签 |
| 用量 | 限额窗口与 token、费用趋势 |

看板下有两个子标签：**待办** 和 **工作树**。在工作树子标签里，每行的更多菜单(⋮)可以
应用(合并)或删除该工作树，并启动、重启、停止它的服务器。

待办行与会话行打开的是同一个弹窗，弹窗分为三个标签页。

| 弹窗标签页 | 内容 |
| --- | --- |
| 概览 | 标题、历史、开工条件与上下文备注全文 |
| 会话 | 会话 id、位置、最近 10 条往来，以及工作区/分类的指定 |
| 工作树 | 该待办用过的工作树 —— 状态、历史与提交 |

## 命令行

`dash.py` 是 Claude Code 使用的入口。所有命令与网页共用同一个数据库，一边的改动在另一边
刷新后即可看到。

### 看板

```bash
python3 dash.py ls                                   # 完整树
python3 dash.py next                                 # 下一件待办
python3 dash.py show <工作区id|JIRA-1>                # 工作区详情
python3 dash.py add-category <名称>
python3 dash.py add-workspace <分类> <名称> [--background ...] [--jira KEY]
python3 dash.py add-todo <标题> [--workspace ID] [--note ...] [--precondition ...]
python3 dash.py move-todo <待办id> --workspace <id|none>
python3 dash.py set-status <todo|workspace> <id> <状态>
python3 dash.py reorder <categories|workspaces|todos> <ids...>
python3 dash.py done-today [--date YYYY-MM-DD]
```

### 会话

```bash
python3 dash.py sessions                             # 正在运行的会话
python3 dash.py classify --category <名称> [--workspace <id>]
python3 dash.py link-todo <待办id> [--status done]    # 让本会话认领一条待办
python3 dash.py show-todo --session
python3 dash.py show-note <待办id>                    # 上下文备注全文
```

会话参数可以省略：省略时 CLI 会退回到 `CLAUDE_CODE_SESSION_ID`，这是 Claude Code 为会话
派生的每个进程都设置的变量。

### 工作树与合并

```bash
python3 dash.py merge                        # 检查 → 拉入目标 → 测试 → 合并 → 释放
python3 dash.py merge --message "标题"        # 合并提交标题
python3 dash.py merge --test "npm test"      # 没有 tests/__main__.py 的仓库
python3 dash.py merge --no-test
python3 dash.py finish [--worktree PATH]     # 仅释放 —— 待办置为 done、停掉服务器
python3 dash.py statusline <会话> [--cwd PATH]
```

`merge` 会在把目标分支拉进工作树之后 **只跑一次** 测试，被测的那棵树就是将被合并的那棵。
如果因冲突中断，解决文件后 `git add`，再执行同一条命令即可接着走。它不会 push，也不会
删除工作树 —— 那是 `ExitWorktree` 的职责。

### 初始设置、语言与自主执行

```bash
python3 dash.py onboard [--skip]             # 是否仍需初始设置
python3 dash.py scan-history --days 7        # 过去每个会话一行摘要
python3 dash.py language [en|ko|ja|zh]       # 不带参数则打印当前值
python3 dash.py usage                        # 限额使用率与 token 趋势
python3 dash.py autorun on|off|status
python3 dash.py autorun-tick [--dry-run]     # 五分钟 cron 调用的入口
python3 dash.py autorun-prompt <待办id>       # 自主会话实际收到的指令全文
python3 dash.py autorun-request "<原因>"      # 暂缓判断，请人来决定
python3 dash.py autorun-finish               # 完成 —— 转入待复核
```

## 与 Claude Code 的集成

### 会话上下文

钩子每个会话只注入 **一个** `<work-dashboard state="...">` 块，注入哪一个取决于看板状态。

| 状态 | 条件 | 注入内容 |
| --- | --- | --- |
| `classified` | 已有工作区，通过分支的 Jira ID 匹配或用 `classify --workspace` 指定 | 背景、目的、目标、注意事项、待办列表与范围约束 |
| `onboarding` | 一个工作区都还没有，且用户也没有拒绝过 | 初始设置流程 |
| `unclassified` | 其余情况 | 当前位置与分支、分类、进行中的工作区，以及分类步骤 |
| `released` | 本会话认领的待办全部为 `done` | 提示把新请求作为新待办接收，而不是压在已完成的待办上 |

分类本身不是自动的 —— shell 无法判断一个问题是关于什么的。钩子只注入指令，由 Claude 用
`classify` 和 `link-todo` 完成登记。

### 钩子

所有钩子在任何失败下都静默 `exit 0`。绝不能因为看板出问题而导致会话打不开或文件改不了。
`exit 2` 只用在「拦截本身就是目的」的场景。

| 钩子 | 事件 | 作用 |
| --- | --- | --- |
| `hooks/dash_hook.py` | `SessionStart`、`UserPromptSubmit`、`Stop`、`SessionEnd` | 注册会话、追踪状态，并注入上面的上下文块 |
| `hooks/worktree_serve.py` | `Stop` | 改过的工作树若没有服务器在跑，则拦截并给出一个空闲端口(9080–9139) |
| `hooks/worktree_guard.py` | `PreToolUse`(`Write`、`Edit`、`NotebookEdit`) | 拦截 `~/work/` 主检出中的源码编辑。`ALLOW_MAIN_CHECKOUT=1` 可绕过 |
| `hooks/commit_scope_guard.py` | `PreToolUse`(`Bash`) | 拦截不带 pathspec 的 `git add -A` 与 `git commit -a`。`ALLOW_BROAD_COMMIT=1` 可绕过 |
| `hooks/md_lint.py` | `PostToolUse`(`Write`、`Edit`、`NotebookEdit`) | 用 `markdownlint-cli2` 检查本仓库中保存的 `.md` |
| `hooks/stale_base.py` | `UserPromptSubmit` | 当分支落后于 upstream 或基准分支时，每个会话提醒一次 |

`worktree_serve.py` 已经登记在本仓库的 `.claude/settings.json` 里，新克隆无需额外配置。
其余五个请以绝对路径登记到 `~/.claude/settings.json`，且路径要指向主检出而不是工作树
—— 工作树在合并后会被删除。

```json
{
  "hooks": [
    {
      "type": "command",
      "command": "python3 /绝对路径/work-dashboard/hooks/dash_hook.py SessionStart",
      "timeout": 2
    }
  ]
}
```

`dash_hook.py` 只接收事件名这一个参数，所以每个事件各加一条，只改最后那个参数即可。

### 状态栏

`~/.claude/statusline-command.js` 会调用 `dash.py statusline <会话> --cwd <路径>`，并把输出
画在用量条下面的第二行。

```text
Context ████░░░░░░ 42% │ Usage ███░░░░░░░ 30% │ Weekly ██████░░░░ 55%
[doing | tab-underline | :9092] 把看板的待办与工作树拆成子标签
```

方括号内固定为 **状态 | 工作树 | 端口**；缺失的部分会连同分隔符一起消失，三者都没有时
方括号本身也不出现。

### 自主执行

开启 `autorun on` 后，五分钟 cron 会挑一条待办，作为后台 `claude` 任务执行。只有带 `auto`
标签的待办才是候选 —— 自主执行的许可由人给出，而不是由代码推测。默认关闭，且没有任何
路径会自动把它重新打开。

```cron
*/5 * * * * /usr/bin/python3 /绝对路径/work-dashboard/dash.py autorun-tick >/dev/null 2>&1
```

没有候选的一次 tick 什么都不做 —— 这正是它是 cron 条目而非常驻守护进程的原因。

## 配置

| 项目 | 位置 |
| --- | --- |
| 数据库 | `~/.claude/work-dashboard/dash.db`，可用 `WORK_DASHBOARD_DB` 覆盖 |
| 主机与端口 | `server.py --host` / `--port`(默认 `127.0.0.1:9080`) |
| 界面语言 | 地球图标，或 `dash.py language`。保存在 `meta.language` |
| 界面文案 | `static/lang/{en,ko,ja,zh}.json`，键完全一致，英语为兜底 |
| 设计 token | `static/css/app.css` 的 `:root` —— 间距、字号与圆角的唯一来源 |
| Markdown 规则 | `.markdownlint.json` |

## 数据模型

SQLite 由网页服务器、CLI 与钩子直接打开，中间没有进程代理。`connect()` 负责建表、开启
外键与 WAL，并只在首次播种六个默认分类。所有 `*_at` 列都是 ISO 8601 UTC 文本。

| 表 | 作用 |
| --- | --- |
| `categories` | 顶层分组，不参与优先级计算 |
| `workspaces` | 一个分支或 Jira 量级的工作，保存背景、目的、目标与注意事项 |
| `todos` | 待办。可以属于某个工作区，也可以直接挂在分类下 |
| `labels`、`todo_labels` | 标签描述待办的性质，一条待办可带多个 |
| `sessions` | Claude Code 会话，由钩子注册与更新 |
| `session_todos` | 会话认领的待办。会话所属工作区由此推导 |
| `worktrees` | 工作树历史，目录被合并或删除后仍保留 |
| `usage_samples` | 用量视图所依赖的限额与 token 采样 |
| `autorun_state`、`autorun_runs` | 自主执行的设置与运行记录 |
| `meta` | 单值设置与内部标志 |

## 项目结构

```text
work-dashboard/
├── dash.py               # CLI 入口 —— 只做解析、委派与输出
├── server.py             # HTTP 入口(http.server，无框架)
├── start.sh              # 后台启动、按日志分文件、保留七天
├── stop.sh · restart.sh  # 只处理本目录的服务器
├── serving.sh            # 服务器探测与停止的公共函数
├── app/
│   ├── constants.py      # 所有魔法数字都集中在这里
│   ├── db.py             # 连接、表结构、事务
│   ├── repositories/     # 按实体划分的存取与一致性规则
│   └── services/         # 跨多个实体的逻辑
├── hooks/                # Claude Code 钩子
├── static/               # ES 模块前端(无打包器)
│   ├── index.html        # 单页。不含文案，只带 data-i18n 键
│   ├── lang/             # en · ko · ja · zh，键集合一致
│   ├── css/              # app.css 定义 token，usage.css 只引用
│   └── js/               # boot、i18n、board、workspace、sessions、usage、chart
├── tests/                # python3 -m tests
└── docs/superpowers/     # 设计文档与计划
```

## 测试

```bash
python3 -m tests
```

测试覆盖仓储层、服务层、CLI 与钩子，校验四个语言文件的键与占位符一致，并强制 CSS 的
间距与字号使用设计 token 而非裸像素值。界面行为检查在 `node` 下运行，由同名的 Python
测试调用。

## 设计文档

`docs/superpowers/specs/` 存放各阶段的设计与既定决策，`docs/superpowers/plans/` 存放实现
计划。
