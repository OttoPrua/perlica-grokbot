# grokbot

给 Perlica / Hermes 用的薄命令：向**已经存在**的云端 webhook dispatcher 发一次
已认证 HTTP POST。HTTP 2xx 只证明收票，不证明异步任务完成。

本仓库**不是**云服务，不直连 xAI API，不伪造 `SendToAgent`，不部署，不发
真实 webhook，不导入私有数据。现有云端例程负责路由和异步执行。

## 效果边界

| 现象 | 含义 |
| --- | --- |
| 客户端尚未 POST | 远端无新效果 |
| HTTP 2xx | 收票。`completed` 恒为 false |
| HTTP 非 2xx、重定向、超时、断连 | 远端效果**未知**；**不重试** |
| 响应正文写 done/completed | 忽略。正文不是完成证据 |

密钥只来自环境变量 `GROK_DISPATCH_WEBHOOK_KEY`：禁止放进 argv、命令输出、
日志、异常或 git。生产 URL 必须是 HTTPS。环回 HTTP 仅用于本仓库合成测试。

## 依赖

- Python 3.9+ 标准库
- 本机已有 dispatcher URL 与 Bearer（由云端例程提供，不由本仓库签发）

```sh
cd <GROKBOT_REPO>
python3 --version
python3 -m grokbot --help
```

## 安装

仓库本身即可运行，不必 pip 安装。

```sh
cd <GROKBOT_REPO>
chmod +x bin/grokbot

mkdir -p "$HOME/.local/bin"
ln -sf "<GROKBOT_REPO>/bin/grokbot" "$HOME/.local/bin/grokbot"

command -v grokbot
grokbot --version
grokbot --help
grokbot --list-targets
```

若 `$HOME/.local/bin` 不在 PATH，把下面这一行放进你的 shell 配置（路径保持
占位，不要提交真实家目录）：

```sh
export PATH="$HOME/.local/bin:$PATH"
```

不建 symlink 时：

```sh
PYTHONPATH=<GROKBOT_REPO> python3 -m grokbot --help
python3 <GROKBOT_REPO>/bin/grokbot --help
```

### 本机环境变量

复制示例到**用户本地**路径，不要提交填好的文件：

```sh
cp <GROKBOT_REPO>/examples/grokbot.env.example "$HOME/.config/grokbot.env"
# 编辑两个占位符：HTTPS URL 与 Bearer
set -a
. "$HOME/.config/grokbot.env"
set +a
```

若 Hermes 已在用 `${HERMES_HOME:-$HOME/.hermes}/.env`（Hermes
`hermes_cli/env_loader.py` 会加载），也可以把同样两个变量追加进那个文件。
仍然不要把密钥写进命令行。

```sh
# 文件内容形态（值保持占位）
GROK_DISPATCH_WEBHOOK_URL=https://<dispatcher-host>/<dispatcher-path>
GROK_DISPATCH_WEBHOOK_KEY=<replace-with-local-bearer-token>
```

## 调用

task 必须非空，并写明日期、URL、目标、期望输出。缺省 target 为 `infra`，
输出里会标明 `target_defaulted`。未知 target **拒绝发送**（不会假装打到
infra）。`daily` 与 `weekly` 作为不同值发送。

```sh
grokbot --dry-run --target 基建 --task "date: 2026-09-08. goal: check toolchain. url: https://example.invalid/runbook. desired output: permissioned status list."

grokbot \
  --target infra \
  --task "date: 2026-09-08. goal: report granted toolchain. url: https://example.invalid/runbook. desired output: status + blocked grants." \
  --reply-to hermes \
  --priority normal

grokbot \
  --target 知识库 \
  --task "date: 2026-09-08. goal: extract one reusable concept. url: https://example.invalid/source. desired output: claim + citation + retain/no-retain." \
  --context "promote only durable concepts, not expiring headlines"

grokbot \
  --target 时效信息 \
  --task "date: 2026-09-08. fact window: 2026-09-08/2026-09-09. url: https://example.invalid/item. desired output: one expiring fact with expires_at."

grokbot \
  --target 日报 \
  --task "cadence: daily. window: 2026-09-07/2026-09-08 +08:00. goal: compose daily pipeline from provided timely and github handoffs. desired output: daily artifact with missing_handoffs listed."

grokbot \
  --target 周报 \
  --task "cadence: weekly. window: 2026-09-01/2026-09-07 +08:00. goal: compose weekly pipeline from provided timely and github handoffs. desired output: weekly artifact with citations to handoffs only."

grokbot \
  --target gh \
  --task "date window: 2026-09-01/2026-09-08. goal: radar on operator watchlist only. desired output: handoff items with repo, event, date, url. if watchlist missing: setup-needed."
```

stdout 为 JSON（`perlica.grokbot.dispatch-result.v1`）。`ok=true` 且
`receipt=true` 仍不是完成。退出码：0 收票或 dry-run；2 用法；3 配置；4 输入；
5 HTTP 非 2xx；6 拒绝重定向；7 超时/断连（未知、无重试）。

目标别名：`infra`/`基建`/`cloud`/`本地基建`；`kb`/`knowledge`/`知识库`；
`timely`/`时效`/`news`/`时效信息`；`daily`/`日报`；`weekly`/`周报`；
`github`/`gh`/`contributor`。

## Hermes 通用放置 vs Perlica 受审发布

命令加一份可移植 Skill 就够，不需要插件脚手架。下面的命令均来自 Hermes /
PerlicaHermes 源码中的真实入口，不是本仓库发明的子命令。

### 通用 Hermes（本仓库即可）

默认 profile 的用户 skill 目录是 `${HERMES_HOME:-$HOME/.hermes}/skills/`
（`get_skills_dir()`）。具名 profile 则是
`${HERMES_HOME:-$HOME/.hermes}/profiles/<PROFILE>/skills/`。

```sh
mkdir -p "${HERMES_HOME:-$HOME/.hermes}/skills/grokbot"
cp <GROKBOT_REPO>/skills/grokbot/SKILL.md \
  "${HERMES_HOME:-$HOME/.hermes}/skills/grokbot/SKILL.md"

hermes skills list
hermes skills list --source local
```

具名 profile：

```sh
mkdir -p "${HERMES_HOME:-$HOME/.hermes}/profiles/<PROFILE>/skills/grokbot"
cp <GROKBOT_REPO>/skills/grokbot/SKILL.md \
  "${HERMES_HOME:-$HOME/.hermes}/profiles/<PROFILE>/skills/grokbot/SKILL.md"
```

项目内 skill（仅当会话 cwd 落在该 git 根，且根目录已信任）：

```sh
mkdir -p <GROKBOT_REPO>/.hermes/skills/grokbot
cp <GROKBOT_REPO>/skills/grokbot/SKILL.md \
  <GROKBOT_REPO>/.hermes/skills/grokbot/SKILL.md
hermes skills trust <GROKBOT_REPO>
```

`hermes skills trust` 写入 `config.yaml` 的 `skills.trusted_project_dirs`。
取消：`hermes skills untrust <GROKBOT_REPO>`。

Hermes 工具 `skill_manage` 也可以在 `~/.hermes/skills/` 创建 skill（不是
shell 子命令）。`hermes skills install` 只接受 hub 标识或 HTTP(S) SKILL.md
URL，**不能**用它指向本仓库本地路径。不要运行 `hermes uninstall`：那会卸
Hermes Agent 本身。

### Perlica 受审源（本仓库不能代替）

Reviewed Skill 源只存在于 PerlicaHermes 的
`profiles/<status>/<profile>/skills/<skill>/`，并由
`registry/perlica-hermes.registry.json#profile_skills` 一对一绑定。运行态
`~/.hermes/profiles/<profile>/skills/` 是可替换投影，不是权威源。

本仓库的 `skills/grokbot/` **不是** PerlicaHermes canonical 源。把文件直接
拷进某个已托管 profile 的运行目录，只会产生 profile-local sediment：受管
发布器必须 fail-closed，不得靠反向同步进 Git。Owner 若晋升这份 skill，需要
另一次受审改动：写入 PerlicaHermes 源树、登记 registry、跑该仓库测试，然后
用 PerlicaHermes 的发布器（在 **PerlicaHermes 检出**里执行，不是本仓库）：

```sh
cd <PERLICA_HERMES_REPO>

ops/live/publish-profile-skill \
  --target-root <EXPLICIT_TARGET_ROOT> \
  --profile <PROFILE> \
  --skill grokbot

ops/live/publish-profile-skill \
  --target-root <EXPLICIT_TARGET_ROOT> \
  --profile <PROFILE> \
  --skill grokbot \
  --canary
```

对 canonical 运行根做 `--apply` / `--retract` 还需要环境变量
`PERLICA_HERMES_LIVE_SKILL_PUBLISH=AUTHORIZED`、
`--expected-source-sha256 sha256:<64-hex>` 与 `--authorization-ref <REF>`。
本候选**不执行**这些 live 步骤，也不把 grokbot 登记进 PerlicaHermes。

## 卸载

```sh
rm -f "$HOME/.local/bin/grokbot"
rm -rf "${HERMES_HOME:-$HOME/.hermes}/skills/grokbot"
rm -rf "${HERMES_HOME:-$HOME/.hermes}/profiles/<PROFILE>/skills/grokbot"
rm -rf "<GROKBOT_REPO>/.hermes/skills/grokbot"
# 若该项目曾被 trust：
hermes skills untrust <GROKBOT_REPO>
# 仅当当初是 hub 安装时才适用：
# hermes skills uninstall grokbot
```

环境文件（`$HOME/.config/grokbot.env` 或 Hermes `.env` 里追加的两行）由你
自己删除。不要用 `hermes uninstall` 来撤 grokbot。

## 云端 bot 初始化

完整、可粘贴的 dispatcher + 五个角色 bot 提示词、平台控制台步骤和首次
watchlist / 时效垂直面检查清单：

[`docs/cloud-bot-initialization.md`](docs/cloud-bot-initialization.md)

五个角色：infra（环境/工具链/媒体，显式权限）、kb（长期知识与引用）、
timely（会过期的单条事实，不是周报流水线）、periodic daily/weekly（流水线
所有者，消费 timely 与 github 交接）、github（用户提供的 watchlist 雷达，
有界沙箱）。缺第一份 watchlist 或时效垂直面是 `setup-needed`，不是编造。

## 测试

只打 `127.0.0.1` 合成服务，使用合成密钥，不访问真实 dispatcher。

```sh
cd <GROKBOT_REPO>
make test
```

## 局限

- 真实云端 URL、密钥、agent id 与异步完成契约不在本仓库。未配置就是
  `setup-needed`。
- 2xx 不是完成；超时/断连后禁止自动重试。
- 客户端拒绝未知 target；云端 dispatcher 对未知名仍可回落到 infra（见提示词）。
- 本候选未做独立隐私/正确性审查，未对公网 git 推送，未向 profile 做 live
  发布。
