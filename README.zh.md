<div align="center">

# dsh-decision-gate

**DSH 的 PreToolUse 决策门禁——对每次 shell 工具调用提五个是非问题，然后放行、询问或拒绝，裁判后端可替换。**

<sub>校准过的阈值、按路径的豁免、JSONL 决策日志——因为联系不上裁判的门禁，绝不能反过来成为卡死 harness 的那个东西。<a href="#工作原理">工作原理 →</a></sub>

[![CI](https://github.com/SeasonTemple/dsh-decision-gate/actions/workflows/ci.yml/badge.svg)](https://github.com/SeasonTemple/dsh-decision-gate/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/SeasonTemple/dsh-decision-gate)](https://github.com/SeasonTemple/dsh-decision-gate/releases)
[![Docs](https://img.shields.io/badge/docs-github%20pages-blue)](https://seasontemple.github.io/dsh-decision-gate/)
[![License: BUSL-1.1](https://img.shields.io/badge/License-BUSL_1.1-blue.svg)](LICENSE)
[![Node >=20](https://img.shields.io/badge/node-%3E%3D20-brightgreen.svg)](https://nodejs.org/)

[English](README.md) · [简体中文](README.zh.md) · [工作原理](#工作原理) · [裁判后端](#裁判后端) · [安装](#安装) · [验证](#验证) · [版本记录](CHANGELOG.md)

</div>

---

DSH（DeepSeek Harness）的 PreToolUse 门禁插件。在每个 shell 类工具调用
（`bash`、`pwsh`、`terminal_*`）执行前，插件向裁判提五个是非问题，按固定
阈值把该调用判为 **allow / ask / deny**，并把每次决策追加写入 JSONL 日志，
供后续用真实数据校准阈值。

这个门禁没有任何提权能力，只做一件事：阻止会话“悄悄做了人不会想做的事”，
其余时候不碍事。

**版本适配。** 已对 DeepSeek Harness `0.2.1-rc.2`（桌面 RC）逐项验证：
进程内门禁挂在 `tools/pre-execute` 接缝上，`0.2.0-rc.1` 之后的每个 RC 都
携带该接缝；支持范围（`>=0.2.0-rc.1 <0.3.0-0`）现在声明在 `package.json`
的 `engines.dsh` 里——harness 自己的插件兼容门读的就是这个字段，版本不符
时 bundle 会被显式跳过而不是带病加载。仓库里的 `hooks.json` 形态是参考实现
和回归基线，不是活门禁；要跑它需要可选的
`@deepseek-ai/dsh-hooks-claude-code` 桥接插件，`0.2.1-rc.2` 桌面版默认
不打包（想用该形态就从插件市场装）。要求 Node >= 20。

---
## 工作原理

对每个受管调用，插件把工具名与参数（每个字符串截断到 8000 字符）发给
TypeSafe SystemOne 接口，带五个 `noul` 问题：

| 信号 | 问什么 |
| --- | --- |
| `read_only` | 是否只读/只查询/只展示，不改动任何状态？ |
| `destructive` | 是否会删除/覆盖他人难以恢复的数据？ |
| `secret_exposure` | 是否会把密钥值发到某处或打印进记录？ |
| `external_irreversible` | 是否不可逆地改变本机之外的状态？ |
| `routine_dev` | 是否是日常本地开发操作？ |

按顺序取第一条命中的规则：

1. `secret_exposure >= 0.50` → **deny**
2. `destructive >= 0.50` → 命中豁免时 **ask**，否则 **deny**
3. `external_irreversible >= 0.50` → **ask**
4. `read_only >= 0.80` → **allow**
5. `routine_dev >= 0.75` → **allow**
6. 其余 → **ask**（`unclear`）

所有故障路径——没有 key、超时、响应不是 JSON、答案形状不对——一律降级为
`next()` 并记录错误。**联系不上裁判的门禁，绝不能反过来成为卡死 harness 的
那个东西。**

## 路径豁免

门禁没有上下文概念，于是 `rm scratch-note.txt` 和 `rm -rf /` 得分完全一样：
destructive、deny、没有申诉通道——agent 将被永久锁死在自己的临时文件上，
因为 deny 无法在会话内被覆盖。

豁免只修这一种情况：当命令的**全部**写目标都落在豁免前缀内（默认
`['.agent-scratch']`）时，destructive 的 deny 降级为 **ask**——人仍然看得到，
但 agent 不会被锁死。解析器刻意做得浅，并且 **fail closed**：

- `secret_exposure` 的 deny 永不降级；
- 有一个目标在前缀外，整条命令不豁免；
- 不认识的动词、解析不了的引号、先 `cd` 再 `rm`、`find -delete`、`xargs rm`、
  符号链接逃逸——全部维持原判。
- 写动词后面还有后续语句（换行分隔）时：裸换行只是空白、不是语句分隔符，
  后续 token 会被继续收进该动词的参数表，成为“额外目标”——额外目标只会让
  命令更不容易被豁免，所以同样 fail closed。想让豁免生效，就把破坏性命令
  保持为单条语句。

```
rm -rf .agent-scratch/old-logs    # ask   （exempt_destructive）
rm -rf src                        # deny  （destructive）
cat .agent-scratch/keys.txt       # deny  （secret 不降级）
rm .agent-scratch/a src/b         # deny  （有目标在前缀外）
```

## 裁判后端

门禁需要一个模型来回答五个是非问题并给出概率。两种后端，由 `judgeProvider`
配置项选择：

- **`typesafe`（默认）**——TypeSafe SystemOne 端点，校准的 `noul` 概率问题：
  亚秒级返回，阈值在这把校准标尺上名副其实。需要 `TYPESAFE_API_KEY`，且**部分
  网络根本到不了**——被区域封锁的出口会拿到 HTTP 451 "not available in your
  region"，每次调用都会 fail open。可配 `typesafeProxy`（或
  `HTTP_PROXY`/`HTTPS_PROXY`）绕开。
- **`dsh-llm`**——同样的五个问题通过会话自己的 LLM 服务（`ctx.llm.stream`）
  发出，跟随 DSH profile 配置的 provider/model：无需额外凭证、没有自己的端点，
  因而不存在区域/代理问题。代价：每条受管调用都要等这个模型（可用
  `model`/`judgeRoute` 钉个快的），且它自报的概率不在阈值所依据的校准标尺上。

两个后端收敛到同一个 `Signals` 对象，所以阈值、豁免、日志格式完全一致，
不管是谁答的。裁判报错、超时、输出不合协议，一律 fail open——门禁记录原因
后放行。

## 配置

配置项（profile 的 `cordis.patch.yml`），均为可选：

| 键 | 默认值 |
| --- | --- |
| `judgeProvider` | `typesafe` |
| `matcher` | `^(bash\|pwsh\|terminal_)` |
| `model` | 随后端而异：`typesafe` 下默认 `jev-1.13.0`；`dsh-llm` 下不设 = 跟随会话当前路由 |
| `judgeRoute` | 不设 = 跟随会话实时的 provider/model；设 `{provider, model}` 则两个都钉死 |
| `logPath` | `<插件目录>/decisions.jsonl` |
| `typesafeApiKey` | 未设：`role('secret')` 字段，表单内掩码编辑、凭证库保管 |
| `typesafeApiKeyEnv` | `TYPESAFE_API_KEY`——未配置密钥时读的环境变量名 |
| `typesafeProxy` | 未设：typesafe 端点的代理 URL（区域封锁的绕行）；留空读 `HTTP_PROXY`/`HTTPS_PROXY`，再否则直连 |
| `destructive` | `0.50` |
| `secretExposure` | `0.50` |
| `externalIrreversible` | `0.50` |
| `readOnly` | `0.80` |
| `routineDev` | `0.75` |
| `exemptPrefixes` | `['.agent-scratch']` |
| `authorizedOperations` | `[]`——按语句匹配，命中后把 external_irreversible 的询问降级为放行 |

鉴权：`dsh-llm` 后端不需要任何额外凭证——它直接搭 DSH 已为该 provider 解析好的
凭证。`typesafe` 后端的密钥按候选解析，profile 配置优先：
`typesafeApiKey`（`role('secret')` 字段——表单内掩码编辑、凭证库保管、不回显）
→ `typesafeApiKeyEnv` 指定的环境变量（默认 `TYPESAFE_API_KEY`）→ Windows 用户
环境（遗留兜底，读一次并缓存）。**表单里配密钥是正规路径**，环境变量是脚本化
部署的候选。

每行决策都记录 `judge`（后端）与 `model`；`dsh-llm` 行另记 `provider`。跨后端切换的日志依然可解读。

## 设置页表单

插件声明了 schemastery `Config` schema，DSH 的 settings 服务会把它投影成
profile 的配置表单（`ctx.settings`）：**裁判后端、钉死的 provider/model、
matcher、日志路径、五个阈值、豁免前缀、预授权操作全部是表单字段**，写入时
校验、持久化进 profile patch、由 Loader 应用——不用重启，也不用手改 YAML。
同样的键在 `cordis.patch.yml` 里依然有效（脚本化部署用）。

卡片出现在插件页的 bundle 详情里，位于描述和组件列表之间。

profile 条目是唯一真源，且**刻意没有环境变量层**——卡片显示的就是实际跑的，
不存在第二种真相。（`hooks/` 下的 Python hook 孪生仍读 `DECISION_GATE_*` 环境
变量：那是 hook 形态唯一的配置通道，属于另一条部署路径。）

schema 运行时需要 `@deepseek-ai/schemastery`，按裸包名从插件自身位置解析
（Node 从模块文件向上找 node_modules）。正常 `npm install`——包括
`dsh plugin add` 为 profile 装的那次——即可提供。

## 安装

一条命令装进任意 profile——挂载行在包自己的 bundle patch 里，**零手动改
profile**：

```bash
dsh plugin --profile web add C:/example/dsh-decision-gate
```

桌面端（CLI 按其设计拒绝操作 desktop profile）走应用内同样的事：**插件页 →
添加插件 → 本地路径 `C:/example/dsh-decision-gate`**。两条路都是把包链接进 profile
并选中 bundle；运行时依赖 `@deepseek-ai/schemastery` 与 `undici` 从 npm 解析。

重启 DSH（或桌面应用）即用，默认开档：校准的 TypeSafe 裁判
（`TYPESAFE_API_KEY`——卡片密钥字段 / 环境变量 / Windows 用户环境三条候选）、
只管 shell 三类工具、下表阈值、`.agent-scratch` 豁免。**被区域封锁的网络**（本网
直连 `api.typesafe.ai` 会拿到 HTTP 451）需要额外钉 `typesafeProxy`——钉在
**profile 自己的 patch 行**里，随包分发的 bundle patch 保持机器中立。

## 配置

每个键都有默认值，零配置安装即可用。要改，在 profile 的 `cordis.patch.yml`
里加一个指向 `decision-gate` 的行：

```yaml
- id: decision-gate
  config:
    judgeProvider: 'dsh-llm'
    destructive: 0.4
```

由于行由 bundle 挂载， stock 安装下设置卡片是**只读**的——它仍然展示每个
生效值和裁判健康度，这是卡片的意义所在。上面那种 profile-patch 行既是配置
通道，也能让卡片恢复可写。

## 卸载

```bash
dsh plugin --profile web remove dsh-decision-gate
```

一步——行在包里，卸包即卸门禁。若想回退到 hook 形态：hook 版就是 `hooks/`
下的文件，经 `hooks/hooks.json` 注册。

## 目录结构

```
lib/index.js          编译产物（宿主半侧，运行时依赖 schemastery 与 undici）
dsh/client.js         浏览器半侧（设置卡片，零构建）
src/index.ts          插件源码
src/parity.ts         Python↔TypeScript 决策对齐测试
hooks/                 Python 孪生实现（规格与回归基线）
tests/                 Python 孪生的 pytest 套件 + hook 配置测试
docs/decision-gate-setup.zh.md（中文）/ docs/decision-gate-setup.md（英文）   部署与验证记录（安装、配置通道、标定复盘）
AGENT.md              给改这个插件的 agent 看的规矩（不进包）
examples/             实时链路测试用的探针 payload
CHANGELOG.md          版本记录
```

`hooks/` 里的 Python 孪生是插件移植前的参考实现；`src/parity.ts` 把它的基线
决策在 TypeScript 侧重放，断言两侧一致。`hooks/exempt.py` 与
`src/index.ts` 中的豁免逻辑逐字镜像，由 `tests/test_exempt.py` 和 `parity.ts`
的离线段用同一张期望表约束——两侧不可能悄悄漂移。

`tests/test_policy.py`、`tests/test_triage.py`、`tests/test_live_path.py`
（以及 `examples/`）是从原工作区一起带出来的：它们测的是同工作区里的另一个
noul-triage 功能，import 它的 `muiltilab` 包。`npm run test:py` 因此只跑
gate 自己的三个测试文件；要跑全套，需要在能 import triage 包的检出里进行。

## 验证

```bash
node tests/functional.mjs   # 14 个 fake-context 用例：双后端、fail-open、日志
node src/parity.ts          # 26 条基线决策 + 30 例豁免 + 3 条降级规则
                            # + 12 例裁判输出解析 + 10 种配置形状
python -m pytest tests -q   # Python 孪生 + hook 配置
```

parity 的离线段不需要 API key；基线决策重放需要 `TYPESAFE_API_KEY`。

校准观察期里，`node tools/observe.mjs` 打印决策分布、裁判错误率、near-miss
放行（危险信号低于阈值）和近期拒绝（供误杀审查）。

部署与标定记录——安装路径、两个配置通道、探针数据表、历次阈值复盘——在
`docs/decision-gate-setup.zh.md（中文）/ docs/decision-gate-setup.md（英文）`。

## 许可

Business Source License 1.1——见 [`LICENSE`](LICENSE)。源码可见，可自由复制、
修改、再分发，非生产使用免费；**生产使用需商业许可**，直到 Change Date
（2030-10-10），此后转为 Apache 2.0。
