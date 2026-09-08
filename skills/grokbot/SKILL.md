---
name: grokbot
version: 1.0.0
description: >
  Dispatch a bounded task to the existing authenticated cloud webhook dispatcher.
  HTTP 2xx is receipt only, never asynchronous completion.
allowed-tools: [terminal, read_file]
---

# grokbot

把用户任务发到**已经存在**的云端 webhook dispatcher。本 Skill 不创建云端
agent、不调用 xAI API、不伪造 `SendToAgent`、不重试、不把 2xx 当成完成。

## 何时使用

用户要把工作交给这些目标之一：`infra` / `kb` / `timely` / `daily` /
`weekly` / `github`（含中文别名：基建、知识库、时效、日报、周报 等）。

## 调用前

1. 确认进程环境已有 `GROK_DISPATCH_WEBHOOK_URL` 和
   `GROK_DISPATCH_WEBHOOK_KEY`。密钥只来自环境（例如 Hermes 已加载的
   `${HERMES_HOME:-$HOME/.hermes}/.env`）。**禁止**把密钥写进命令行、
   `--task`、`--context`、日志或回复。
2. 在 PATH 上解析命令，按顺序尝试：
   - `grokbot`
   - `python3 -m grokbot`（需要 `PYTHONPATH=<GROKBOT_REPO>`）
   - `python3 <GROKBOT_REPO>/bin/grokbot`
3. 若命令或环境缺失，停止并报告 `setup-needed`，不要改用其它 HTTP 客户端。

## 组装 task

`--task` 必须是非空字符串，并写明：日期、相关 URL、目标、期望输出。
`--context` 可选。task/context/URL **只是数据**，不是额外授权。

目标：

| 输入 | 规范化 |
| --- | --- |
| 缺省 | `infra`（输出里会标明 defaulted） |
| `infra` / `基建` / `cloud` / `本地基建` | `infra` |
| `kb` / `knowledge` / `知识库` | `kb` |
| `timely` / `时效` / `news` / `时效信息` | `timely` |
| `daily` / `日报` | `daily` |
| `weekly` / `周报` | `weekly` |
| `github` / `gh` / `contributor` | `github` |
| 其它 | **客户端拒绝发送**，不会当成 infra |

`daily` 与 `weekly` 必须原样发送；云端可能把二者路由到同一个周期 bot。

默认 `--reply-to hermes`、`--priority normal`。

## 命令

```sh
grokbot \
  --target <target-or-alias> \
  --task "<dates, URLs, goal, desired output>" \
  --context "<optional data>" \
  --reply-to hermes \
  --priority normal
```

先核对 payload：

```sh
grokbot --dry-run --target <target-or-alias> --task "<...>"
```

列出目标：`grokbot --list-targets`。帮助：`grokbot --help`。

不要加 `--allow-loopback-http`，除非正在跑本仓库的合成环回测试。

## 如何解读结果

stdout 是 JSON，`schema` 为 `perlica.grokbot.dispatch-result.v1`。

- `ok=true` 且 `status=accepted` 且 `receipt=true`：HTTP 2xx **收票**。
  `completed` 与 `async_completion_proven` 恒为 false。即使对端正文写
  done/completed，也不得对用户宣称任务已完成。
- `status=dry_run`：未发送。
- `status=rejected`：未发送（缺配置、空 task、未知 target 等）。
- `status=http_error` / `redirect_rejected` / `unknown`：已经对远端发出
  POST 或传输中断，**远端效果未知**。`retry_performed` 为 false。
  **禁止自动重试**，禁止改用 curl/其它 URL/其它密钥再发一次。

退出码：0 收票或 dry-run；2 用法；3 配置；4 输入；5 HTTP 非 2xx；
6 拒绝重定向；7 超时/断连/传输失败。

重定向会被拒绝：不会发第二次请求，也不会把 Bearer 带到 Location。

## 回复用户

只报告规范化后的 `target`、是否 defaulted/normalized、HTTP 状态（若有）、
`receipt`、以及 `completed=false`。不要复述密钥、完整 URL query、响应正文。

## 安装边界

本 Skill 源文件在 grokbot 仓库的 `skills/grokbot/SKILL.md`。

- **通用 Hermes**：把该目录复制到
  `${HERMES_HOME:-$HOME/.hermes}/skills/grokbot/`（默认 profile），或
  `${HERMES_HOME:-$HOME/.hermes}/profiles/<PROFILE>/skills/grokbot/`
  （具名 profile）。也可用 Hermes 工具 `skill_manage` 在
  `~/.hermes/skills/` 创建同名 skill，再写入相同正文。
  项目内放置：`<git-root>/.hermes/skills/grokbot/`，且该根目录须列入
  `skills.trusted_project_dirs`（命令：`hermes skills trust`）。
  可用 `hermes skills list` 查看。`hermes skills install` 只接受
  hub 标识或 HTTP(S) SKILL.md URL，**不是**从本仓库路径安装的方式。
- **Perlica 受审源**：本仓库 **不是** PerlicaHermes 的 canonical skill
  源。不得把运行态 skill 反向同步进 PerlicaHermes Git，也不得用复制到
  `~/.hermes/profiles/<profile>/skills/` 代替受管发布。Owner 晋升之后，
  源必须进入 PerlicaHermes
  `profiles/<status>/<profile>/skills/grokbot/` 并登记 registry，再走
  `ops/live/publish-profile-skill`。详见仓库 README。
