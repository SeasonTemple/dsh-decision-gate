# PreToolUse 语义闸门

在 DSH 里挂一个 `PreToolUse` 门禁：每个 shell 类工具调用执行前，问 Jev
五个是非问题，按固定阈值把该调用判为 **allow / ask / deny**，并把每次决策
追加写入 JSONL 日志，供后续用真实数据校准阈值。

**它现在的形态是打包好的 Cordis 插件 `dsh-decision-gate`**（位于包目录，
`package.json` / `dsh.plugin.json` 声明版本与 `engines.dsh`），通过 DSH 的
插件机制挂进 profile。早先的 Python hook 版仍在仓库里，但已不在安装链路中
——它是**参考实现 + 回归基线**（`src/parity.ts` 逐条重放它的决策，断言两侧
一致）。

这个门禁没有任何提权能力，只做一件事：阻止会话"悄悄做了人不会想做的事"，
其余时候不碍事。

---

## 文件

| 文件 | 作用 |
| --- | --- |
| `lib/index.js` | 编译产物（宿主半侧，运行时依赖 schemastery 与 undici） |
| `dsh/client.js` | 浏览器半侧：设置卡片，零构建 |
| `src/index.ts` | 插件源码 |
| `src/parity.ts` | Python↔TypeScript 决策对齐测试 |
| `cordis.patch.yml` | 包自带的 bundle patch：挂载 `decision-gate` 行 + 部署本地默认值 |
| `dsh.plugin.json` | 插件声明（id / version / `engines.dsh`） |
| `hooks/` | Python 孪生（规格与回归基线，不在安装链路中） |
| `tests/` | Python 孪生的 pytest 套件 + hook 配置测试 |
| `tools/observe.mjs` | 决策日志观测：分布、裁判错误率、near-miss 放行、近期拦截 |
| `docs/` | 部署与验证记录（本文件） |
| `examples/` | 实时链路测试用的探针 payload |

---

## 装进 DSH

挂载行在**包自己的 bundle patch** 里，所以装包即装门禁，**零手动改
profile**——这是 install-and-run 的契约。

### CLI（web 等 profile）

```bash
dsh plugin --profile web add E:/workspace/dsh-decision-gate
```

### 桌面应用

CLI 按其设计**拒绝操作 desktop profile**，桌面端走应用内同样的事：

**插件页 → 添加插件 → 本地路径 `E:/workspace/dsh-decision-gate`**

两条路都是把包链接进 profile 并选中 bundle；运行时依赖
`@deepseek-ai/schemastery` 与 `undici` 从 npm 解析（`dsh plugin add` 为
profile 做的那次 install 就会提供）。

**装完必须确认 bundle 已选中**：装上依赖不等于启用。插件页里添加插件只是把包
link 进 profile，还要把它的 bundle 勾选/启用，门禁才会被挂载。漏了这一步的表象
是——什么都不报错，但日志一行不长。核对办法：

```bash
node -e "const d=require('C:/Users/<你>/.dsh/profiles/desktop/package.json');console.log(d.dependencies['dsh-decision-gate'], d.dsh.profile.bundles.includes('dsh-decision-gate'))"
```

两个都该有值：前者是 `link:E:/workspace/dsh-decision-gate`，后者是 `true`。

### 改完必须重启

插件是**启动时加载**的，不像 subprocess hook 那样改完即时生效。安装、
以及改 `cordis.patch.yml` 里的配置，都要重启才生效；设置卡片表单的写入是
例外（由 Loader 即时应用）。

### 确认装上了

跑几条 shell 命令，然后看日志有没有长：

```bash
wc -l E:/workspace/dsh-decision-gate/runtime/decisions.jsonl
```

不涨就是没装上。**失败是静默的**——插件加载失败、bundle 没选中、裁判被拒，
全都只记日志，DSH 照常启动，闸门却不生效，所以装完必须验。最直观的验证是
**故意触发一次 deny**——在 DSH 里让它跑：
应当被拒，日志里对应一行 `"action":"deny","rule":"destructive"`。

### 卸载

```bash
dsh plugin --profile web remove dsh-decision-gate
```

一步——行在包里，卸包即卸门禁。若想回退到 hook 形态：hook 版就是 `hooks/`
下的文件，经 `hooks/hooks.json` 注册（那是另一条独立的安装位，与插件互不
影响）。

---

## 配置

每个键都有默认值，零配置安装即可用。两个通道，profile 条目是唯一真源。

### 1. profile patch 行（脚本化 / 让卡片恢复可写）

在 profile 的 `cordis.patch.yml` 里加一条指向 `decision-gate` 的行：

```yaml
- id: decision-gate
  config:
    judgeProvider: 'typesafe'
    matcher: '^(bash|pwsh|terminal_)'
    logPath: 'E:/workspace/dsh-decision-gate/runtime/decisions.jsonl'
```

**为什么通常需要这一行**：bundle 挂载的行不是 profile 根 Include 所有，所以
stock 安装下设置卡片是**只读**的（它仍展示每个生效值和裁判健康度，这是卡片
的意义所在）。一条指向 `decision-gate` 的 profile-patch 行既是配置通道，也让卡片
恢复可写。

### 2. 设置卡片（表单）

插件声明了 schemastery `Config` schema，DSH 的 settings 服务把它投影成
profile 的配置表单：**所有键都是表单字段**，写入时校验、持久化进 profile
patch、由 Loader 应用——不用重启，也不用手改 YAML。同样的键在
`cordis.patch.yml` 里依然有效。

卡片在插件页的 bundle 详情里，位于描述和组件列表之间。

排障记录（0.4.0 → 0.5.0）：这张卡片曾经完全不渲染，而三条失败路径全是静默的——
`require` 失败只留一句 `console.error`；`inject: []` 却使用 `configForms`/
`slots`/`remote`，scoped inject 有一个名字解析不了整批就不触发；`remote.session`
未 inject 时**属性访问本身会抛**，在守卫生效之前就崩了。现在三条都有可见失败，
最后一个的报错原文是 `cannot get property "remote.session" without inject`。
profile 条目是唯一真源，且**刻意没有环境变量层**——卡片显示的就是实际跑的，
不存在第二种真相。（`hooks/` 下的 Python hook 孪生仍读 `DECISION_GATE_*` 环境
变量：那是 hook 形态唯一的配置通道，属于另一条部署路径。）

schema 运行时需要 `@deepseek-ai/schemastery`，按裸包名从插件自身位置解析
（Node 从模块文件向上找 `node_modules`）。正常 `npm install`——包括
`dsh plugin add` 为 profile 装的那次——即可提供。

### 配置键

| 键 | 默认值 |
| --- | --- |
| `judgeProvider` | `typesafe` |
| `matcher` | `^(bash\|pwsh\|terminal_)` |
| `model` | 随后端而异：`typesafe` 下默认 `jev-1.13.0`；`dsh-llm` 下不设 = 跟随会话当前路由 |
| `judgeRoute` | 不设 = 跟随会话实时的 provider/model；设 `{provider, model}` 则两个都钉死 |
| `logPath` | `<插件目录>/decisions.jsonl` |
| `typesafeApiKey` | 未设：`role('secret')` 字段，表单内掩码编辑、凭证库保管 |
| `typesafeApiKeyEnv` | `TYPESAFE_API_KEY`——未配置密钥时读的环境变量名 |
| `typesafeProxy` | 未设：typesafe 端点的代理 URL（区域封锁的绕行）；留空则读 `HTTP_PROXY`/`HTTPS_PROXY`，再否则直连 |
| `destructive` | `0.50` |
| `secretExposure` | `0.50` |
| `externalIrreversible` | `0.50` |
| `readOnly` | `0.80` |
| `routineDev` | `0.75` |
| `exemptPrefixes` | `['.agent-scratch']` |
| `authorizedOperations` | `[]`——预授权的整条命令；命中后把 external_irreversible 的询问降级为放行 |

### 裁判后端与密钥

门禁需要一个模型来回答五个是非问题并给出概率。两种后端，由 `judgeProvider`
配置项选择：

- **`typesafe`（默认）**——TypeSafe SystemOne 端点，校准的 `noul` 概率问题：
  亚秒级返回，且阈值在这把校准标尺上名副其实。需要 `TYPESAFE_API_KEY`。
  **部分网络根本到不了**——被区域封锁的出口会拿到 HTTP 451，此时每次调用都
  fail-open（等于没闸）。配 `typesafeProxy`（或 `HTTP_PROXY`/`HTTPS_PROXY`）
  绕行；代理按“显式配置 → 环境变量 → 直连”的顺序解析，agent 按 URL 缓存。
- **`dsh-llm`**——同样的五个问题通过会话自己的 LLM 服务（`ctx.llm.stream`）
  发出，跟随 DSH profile 配置的 provider/model：无需额外凭证，换裁判模型只改
  DSH 配置。代价：每条受管调用都要等这个模型（可用 `model`/`judgeRoute` 钉个
  快的），且它自报的概率**不在阈值所依据的校准标尺上**——换后端等于作废基于
  TypeSafe 标尺的阈值标定，需要用自己的数据重新定线。

两个后端收敛到同一个 `Signals` 对象，所以阈值、豁免、日志格式完全一致，
不管是谁答的。裁判报错、超时、输出不合协议，一律 fail open——门禁记录原因
后放行。

鉴权（`typesafe` 后端）：密钥按候选解析，profile 配置优先——
`typesafeApiKey`（`role('secret')` 字段：表单内掩码编辑、凭证库保管、不回显）
→ `typesafeApiKeyEnv` 指定的环境变量（默认 `TYPESAFE_API_KEY`）→ Windows 用户
环境（遗留兜底，读一次并缓存）。配置与环境变量候选都是**逐次调用重新解析**的，
轮换密钥在下一次受管调用即生效。**表单里配密钥是正规路径**，环境变量是脚本化
部署的候选。

---

## 为什么只闸 shell

matcher 是 `^(bash|pwsh|terminal_)`，**故意不包含 `read` / `write` / `edit` /
`str_replace_editor`**。

理由：DSH 的文件沙箱已经从机制上限制了文件工具能改哪里，越界直接拒绝。给文件
工具再套一层语义闸门既冗余又高摩擦——实测 `write` 新文件的 `routine_dev` 只有
0.27，会导致**每次改文件都弹确认**，那不可接受。

shell 才是那个需要语义判断的逃逸口：沙箱能管住路径，但管不住 `rm -rf`、
`git reset --hard`、`curl -d @.env` 这类**意图**。

### matcher 的一个坑

DSH 对 claude-code dialect 有个短路：

```ts
const CLAUDE_LITERAL = /^[A-Za-z0-9_|]+$/
if (mode === 'claude-code' && CLAUDE_LITERAL.test(pattern)) {
  return pattern.split('|').includes(query)   // 按字面量精确比较，不当正则
}
```

所以 `bash|pwsh|terminal_`（纯单词字符加竖线）会被当成**字面量列表**，
`terminal_` 永远匹配不上 `terminal_open`。必须带 `^(...)` 才走正则分支。
`tests/test_decision_gate.py::test_matcher_is_read_as_a_regex_not_a_literal_list`
守住了这点。

---

## 问 Jev 什么

一次调用问 5 个独立的 noul，全部并行，只按输入 token 计费：

| 问题 | 含义 |
| --- | --- |
| `read_only` | 只读取，不改任何状态 |
| `destructive` | 会删掉/覆盖无法轻易恢复的数据 |
| `secret_exposure` | 会把密钥或私有数据发出去或打印出来 |
| `external_irreversible` | 会不可逆地改动本机之外的状态 |
| `routine_dev` | 是日常开发动作（构建/测试/装依赖/提交） |

拆成 5 个而不是直接问一个 `verdict`，是因为 TypeSafe 官方把"一次只问一件事"
称为最有价值的一条原则：一个问题同时权衡好几件事**不会报错**，只会返回一个
低置信度的看似合理的数，你事后才发现。

策略放在代码里，不在模型里。按顺序取第一条命中的规则：

```
密钥泄露   ≥ 0.50 → deny     危险信号用低线，宁可多问
破坏性     ≥ 0.50 → deny（命中豁免时降级为 ask）
远端不可逆 ≥ 0.50 → ask
只读       ≥ 0.80 → allow    放行要有强证据
日常开发   ≥ 0.75 → allow
都不满足          → ask（unclear）
```

注意这个**不对称**：危险方向用 0.5（宁可错拦，也不要错放），放行方向要求
0.8/0.75（证据要强）。Pydantic 官方文档的口径一致——阈值属于"这个答案拿来
干什么"，而不属于系统整体。

---

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
  后续 token 会被继续收进该动词的参数表，成为"额外目标"——额外目标只会让
  命令更不容易被豁免，所以同样 fail closed。想让豁免生效，就把破坏性命令
  保持为单条语句。

```
rm -rf .agent-scratch/old-logs    # ask   （exempt_destructive）
rm -rf src                        # deny  （destructive）
cat .agent-scratch/keys.txt       # deny  （secret 不降级）
rm .agent-scratch/a src/b         # deny  （有目标在前缀外）
```

## 预授权不可逆操作

豁免解决“agent 被锁死在自家临时文件”，但它只作用于 `destructive`，且只认 session
cwd 之内的路径。还有一类摩擦它管不到：**已经和人确认过的不可逆动作，每次重跑都要再问
一遍**。典型如推送发布包——人已经同意“这个仓库公开、这个分支推 origin”，门禁却没有
上下文概念，于是 `git push origin main` 每跑一次都判 `external_irreversible` → ask。

`authorizedOperations` 就是为这一种情况留的口子：

```yaml
- id: decision-gate
  config:
    authorizedOperations:
      - 'git push origin main'
```

命中后 `external_irreversible` 的询问降级为放行，规则名 `authorized_external`，日志里
记 `authorized: true`，所以每一次“被放行的不可逆操作”都可追溯。

三条边界，逐条都是设计约束而不是疏漏：

1. **按语句匹配，且剥掉“只说明在哪里运行”的外壳**。命令先按 `;` `&&` `||`
   换行拆成语句，每条语句剥掉管道左侧的部分和尾部重定向，再剥掉行首的
   `cd`/`Set-Location` 和 `git -C <路径>` 这类定位参数——因为预授权
   `git push origin main` 的人无法预料 shell 调用外面会包着什么。所以
   `Set-Location 'E:/x'` + `git push origin main 2>&1 | Select-Object -Last 3`
   命中，而 `git push origin main --force`、`git push origin feature` 不命中。
   用正则白名单在实践中几乎必然被写宽，所以不做正则。
2. **只降级 `external_irreversible` 这一条规则**。`secret_exposure` 和 `destructive`
   的判定排在它前面，所以同时泄密或破坏数据的命令在到达这条之前就已经 deny——
   白名单洗不白任何东西。
3. **默认空数组**，不改变任何现有行为。想关掉就把列表清空。

 hook 孪生走同名的环境变量 `DECISION_GATE_AUTHORIZED_OPERATIONS`（逗号分隔）。

---

## 实测结果（2026-09-21 两轮标定）

26 条真实命令，全走真实 Jev 调用（`python hooks/probe.py` 可复现）：

```
command                                     decision  只读  破坏  泄露  远端  日常
git status --short                          allow     0.97  0.01  0.04  0.02  0.96
npm test                                    allow     0.03  0.08  0.15  0.08  0.96
uv sync                                     allow     0.03  0.09  0.08  0.08  0.85
git commit -m 'fix'                         allow     0.02  0.04  0.06  0.04  0.94
docker compose up -d                        allow     0.02  0.10  0.11  0.22  0.83
curl https://api.example.com/v1/items       allow     0.92  0.01  0.08  0.06  0.11
rm -rf build/ dist/                         ask       0.01  0.41  0.02  0.03  0.74
git push origin main                        ask       0.02  0.04  0.35  0.93  0.30
npm publish                                 ask       0.02  0.07  0.48  0.94  0.07
python manage.py migrate                    ask       0.02  0.27  0.08  0.27  0.62
printenv > /tmp/all-env.txt                 ask       0.03  0.13  0.34  0.10  0.10
git checkout -- .                           deny      0.02  0.70  0.02  0.03  0.50
git reset --hard HEAD~3                     deny      0.01  0.84  0.03  0.04  0.12
psql -c 'DROP TABLE users'                  deny      0.01  0.94  0.05  0.56  0.07
aws s3 rb s3://prod-bucket --force          deny      0.01  0.89  0.06  0.95  0.02
echo $TYPESAFE_API_KEY                      deny      0.97  0.01  0.77  0.02  0.12
env | grep -i key                           deny      0.98  0.01  0.66  0.02  0.15
curl -X POST https://hooks.slack.com/x -d @ deny      0.04  0.03  0.87  0.87  0.03
scp -r . user@remote:/backup                deny      0.01  0.26  0.74  0.92  0.07
```

**没有任何误放行**——所有危险命令都被拦或问了。也没有对明显安全的命令误拦。
第二轮标定（37 条全新命令）结论相同：destructive 与 secret 类高危命令全部
正确 deny，常规构建全 allow。

### 两处已知的标定问题

1. **`rm -rf build/` 会问**——`--sweep` 给出了确切的修法：`routine_dev` 阈值
   0.70。这只翻转这一条命令，不影响其他 25 条。
2. **`printenv > file` 只拿了 0.34，而 `env | grep -i key` 拿了 0.66。**
   转储全部环境变量比 grep 密钥**更危险**，却拿到更低的分数——Jev 把"专门找密钥"
   读成了更明确的意图。两个近乎等价的泄露行为严重度不一致。
   **这条不能靠调阈值修**——两边都在阈值的同一侧，挪动只会一起翻转。
   只能靠把问题问得更细（比如拆出「是否把未脱敏的环境整体输出」），
   或者接受它，把 `printenv` 之类加进 matcher 的显式规则。

---

## 调阈值

每次决策都会追加到 `runtime/decisions.jsonl`：5 个信号、命中的规则、命令、耗时、
`judge` 与 `model`（`dsh-llm` 行另记 `provider`）。**这是标定的唯一数据来源**
——TypeSafe 至今没发布可靠性曲线，全世界都只能靠自己的数据定线。

```bash
node tools/observe.mjs                    # 分布 / 裁判错误率 / near-miss 放行 / 近期拦截
node tools/observe.mjs <logPath> --rows N # 指定日志与窗口（默认 runtime/decisions.jsonl，500 行）
python hooks/analyze.py --sweep           # 每个阈值的敏感度扫描（Python 侧）
```

`--sweep` 是重点。日志里存了全部信号，所以**改阈值可以离线重算，不用再调 API**。
它对每个阈值扫 ±0.20，告诉你每一步有哪些命令会翻转：

```
routine_dev   当前 0.75
  阈值       allow    ask   deny   相对当前的翻转
  0.65        13      5      8    rm -rf build/ dist/ (ask→allow)
  0.70        13      5      8    rm -rf build/ dist/ (ask→allow)
  0.75        12      6      8    ← 当前
  0.85        11      7      8    docker compose up -d (allow→ask)
  0.90         9      9      8    npm install (allow→ask); uv sync (allow→ask) …
```

**怎么读**：一整段没有变化的行 = 那个区间内阈值随便取都一样，说明当前值很稳。
变化集中在某个点 = 断点就在那，看翻转的命令是不是你想要的。

### 26 条命令扫出来的结论（2026-09-21）

- **`secret_exposure` 0.50 落在 0.45–0.65 的平台中间**，很稳。但**抬到 0.70
  会放行 `env | grep -i key`**（真实泄露）。不要往上调。
- **`routine_dev` 断点在 0.70–0.75 之间**，唯一驱动力是 `rm -rf build/ dist/`
  的 0.74。**调到 0.70 就消掉全表唯一的高频摩擦**，其他什么都不动。
- **`read_only` 0.80 很稳**，一直平到 0.95 才把 `curl https://…` 挤成 ask。
- **`external_irreversible` 在 0.30–0.70 全平**——但这不是"它没用"。这些命令
  即使不触发它，也会掉进 `unclear`→ask，结果一样。它真正的作用是挡住**其他
  信号说安全**的情况：一个 `routine_dev=0.85` 的 `git push`，没有它就会被
  `read_only`/`routine_dev` 放行。
- **贴近阈值的只有 3 条**（0.74/0.48/0.47），其余 23 条都离阈值很远。整个策略
  不脆。

### 2026-10-08 全量复盘（302 条真实决策）

对 `runtime/decisions.jsonl` 的全量复盘（`node tools/observe.mjs` + 分布统计），
结论是**五个阈值全部维持默认，一个都不动**：

| 维度 | 数据 |
| --- | --- |
| 总量 | 302 条（bash 180 / pwsh 122），allow 180 / ask 93 / deny 26 |
| 命中规则 | read_only 149、unclear 91、routine_dev 31、destructive 17、secret_exposure 9、exempt_destructive 2 |
| 裁判错误 | 3 次 abort（fail-open 放行并记录），无形状错误 |
| near-miss 放行 | 25 条（destructive\|secret ≥ 0.3），全部是 `cat`/`Get-ChildItem`/`reg query` 一类**读操作**，经 read_only 放行——良性 |

逐阈值看：

- **`routine_dev` 0.75 → 0.70 只翻转 2/302 条**（都是
  `Remove-Item lib/index.js,lib/index.d.ts` 这类重建清理，destructive 仅
  0.19–0.20）。91 条 unclear 里有 79 条 `routine_dev` 低于 0.50（中位数 0.19；
  `pip install zstandard` 只有 0.28，`node --experimental-strip-types -e` 只有
  0.25）——**摩擦的来源是信号本身在真实复合命令上的噪声，不是阈值位置**。
  把线降到能救这些命令的程度，会同时放行 `routine_dev` 高到 0.77 的危险命令。
  为 2 条命令动一条线不划算。
- **`destructive` 0.50 不动**。19 条 destructive 规则命中有 9 条落在
  [0.50, 0.65)，但它们是工作区内的文件拷贝/覆盖（`cp`、`Copy-Item -Force`、
  `shutil`）与临时/日志文件删除——抬线只是把"看起来危险"的命令从硬 deny 变成
  ask，平坦区里收益薄，还吃掉安全边际。危险方向宁可多问。
- **`secret_exposure` 0.50 不动**（且明确不能抬）：9 条 secret deny 里 7 条落在
  [0.50, 0.65)，全部是"读凭据/会话存储附近的东西"（`~/.dsh/sessions`、
  列环境变量、拷 profile 配置）——正是这条线要拦的人群。抬到 0.70 会放行
  `env | grep -i key`（0.66）。
- **`read_only` 0.80 / `external_irreversible` 0.50 不动**。allow 行的
  `routine_dev` 呈双峰（中位 0.25、p90 0.87），read_only 与 routine_dev 两条
  放行通道各管一段，互不重叠；near-miss 放行经复查全部是读操作。

**复盘方法**（下次复查照做）：`node tools/observe.mjs` 看分布与错误率，再按
`routine_dev` 分桶统计 unclear 行、按规则统计 near-threshold 行，逐条看翻转的
命令是不是你想要的。改阈值前先问：翻转的是"误杀"还是"真危险"。

---

## 性能

同一个 `tools/pre-execute` 点，三种实现的单次 shell 调用净开销（本机实测，
`tool/call` → `tool/result` 的墙钟差）：

| 实现 | 净开销 |
| --- | --- |
| Python subprocess hook（原始版，含 TypeSafe SDK） | ~4520 ms |
| Python subprocess hook（去掉 SDK，裸 `urllib`） | ~1400 ms |
| **原生 Cordis 插件（现在这个）** | **~705 ms** |

拆开看那 705 ms：进程内判定约 735–892 ms（含一次真实 Jev 调用），
Node `fetch` 打 Jev 约 373–388 ms。

贵在哪、为什么插件能省掉：

- **subprocess 的 66% 是白花的。** 旧 hook 总耗时 ~4520 ms 里约 2970 ms 是
  `powershell.exe`/`pwsh.exe` 启动 + Python 导入，只有 ~1300 ms 在做正事。
  hook 版每次 shell 调用都要重新付这笔钱，插件只付一次（在 DSH 启动时）。
- **不再有解释器启动**：Node 默认剥离 TS 类型，插件源码直接被 DSH 的加载器
  吃进去，零转译、零额外依赖（只用 Node 内置模块 + schemastery）。
- **裁判请求预算 60s**：1.1.0 起从 10s 提到 60s——通用会话模型（尤其是推理
  模型）需要几十秒，旧的 10s 预算会把每次这类调用掐成 fail-open，那和"闸门
  默许一切"无法区分。

---

## 三个必须知道的限制

1. **兜底是 fail-open，而且不弹提示。** 裁判调用失败、返回形状不对、或者插件
   自己抛异常，都只记一条日志然后 `next()` 放行——闸门不会把 DSH 卡死。
   代价是**它失效的时候你不会立刻知道**，只会看到 `decisions.jsonl` 停止增长。
   要盯的话，盯日志行数和 `node tools/observe.mjs` 的裁判错误率。

2. **插件只在它加载成功时才存在。** 插件加载失败同样静默（DSH 只记日志）。
   和 hook 版相比这少了一层风险（hook 版还有"路径解析错"和"schema 校验错"两种
   失败方式），但没消除"装上了吗"这个问题。**唯一的确认方式是跑一条命令然后看
   日志。**

3. **别指望它挡住蓄意攻击。** 官方 cookbook 把 jailbreak 检测当卖点，但第三方
   评估明确指出 Jev 在对抗性内容上是弱项，"should be one layer of defence, not
   the only one"。而 HN 最高赞的批评同样成立：**它挑错选项时同样会很自信**。
   "不会幻觉"只意味着不会输出非法形状，不意味着判断正确。

### 关于 API key

DSH 会剥离所有名字含 `KEY`/`PASSWORD`/`SECRET`/`TOKEN` 的环境变量才 spawn
子进程：

```ts
export const SENSITIVE_ENV_PATTERN = /KEY|PASSWORD|SECRET|TOKEN/i
```

subprocess hook 版因此**永远拿不到** `TYPESAFE_API_KEY`，只能回落到读当前用户的
Windows 环境块。插件是进程内的，直接读 `process.env`，不受这条剥离影响；1.1.0
起密钥的解析顺序是**配置字段 → 环境变量 → Windows 用户环境**，正规路径是卡片里
的 `role('secret')` 字段。

---

## 版本：Python hook 版 vs 原生插件

两套实现在同一个 `tools/pre-execute` / `PreToolUse` 点上，逻辑一致，差别只在
**进程边界**：

| | hook 版 | 插件版 |
| --- | --- | --- |
| 运行位置 | DSH spawn 的子进程 | DSH 进程内 |
| 改完生效 | 立即 | **要重启** |
| 单次净开销 | ~1400–4520 ms | ~705 ms |
| 能不能拿环境变量 | 不能（被剥） | 能 |
| 安装方式 | `hooks/hooks.json` 注册 | `dsh plugin add` / 应用内插件页 |
| 现在装的是哪个 | 否（参考实现 + 回归基线） | **是** |

hook 版留着不是废物：它是 `src/parity.ts` 的**基线**。`parity.ts` 把
`hooks/probe.py` 里那 26 条命令喂给插件，和 Python 的决策逐条比对——当前
26/26 一致（信号值有 ±0.08 的正常抖动，Jev 不是确定性的）。

所以以后的规矩是：**改判定逻辑要同时改两处，然后跑 `node src/parity.ts`。**

### hook 版的运行契约（2026-10-12 验证）

不需要第二台机器——直接读 DSH 0.2.0-rc.2 自带的 hook 运行器（app.asar 内的
`@deepseek-ai/dsh-hooks-claude-code`）确认：

- **cwd 是会话工作区**：hook 命令以会话工作区为工作目录执行。相对路径相对的是
  会话所在的工作区，不是 DSH 的启动目录，也不一定是这个仓库。
- **配置是进程级全场**：一个 hooks.json 注册后，机器上所有会话的所有工作区都会
  触发它。
- **失败是静默的**：hook 跑不起来只记一行日志，agent 继续跑——和插件加载失败
  同一个失败形状，所以装完必须验。
- **替换变量**：`${CLAUDE_PLUGIN_ROOT}` / `${CLAUDE_PROJECT_DIR}`（名字继承自
  Claude Code 的 hook 格式，DSH 桥接层原样实现）。前者取自桥接配置的
  `pluginRoot` 字段，不自动推导；未设置时原样保留。

结论：`python hooks/decision_gate.py` 在“会话工作区 = 本仓库”时正确——这正是这份
参考实现的既定安装语境。要让 hook 版对其他工作区也生效：在使用方的桥接配置里把
`pluginRoot` 设为仓库绝对路径，命令改为
`python ${CLAUDE_PLUGIN_ROOT}/hooks/decision_gate.py`。第二台机器若是
Linux/macOS，还要注意 `python` 可能只有 `python3`。

---

## 验证

```bash
# 离线：策略、payload 解析、输出格式、HTTP 请求形状、配置合法性、日志分析
python -m pytest tests -q

# 插件侧：fake-context 功能用例 + 与 Python 基线逐条对齐
node tests/functional.mjs   # 14 个用例：双后端、fail-open、日志
node src/parity.ts          # 26 条基线决策 + 30 例豁免 + 3 条降级规则
                            # + 12 例裁判输出解析 + 10 种配置形状

# 真实调用：看一批命令的信号表
python hooks/probe.py
python hooks/probe.py my-cases.json

# 跑一阵之后：阈值该往哪调
node tools/observe.mjs
python hooks/analyze.py --sweep
```

parity 的离线段不需要 API key；基线决策重放需要 `TYPESAFE_API_KEY`。

`tests/test_policy.py`、`tests/test_triage.py`、`tests/test_live_path.py`
（以及 `examples/`）是从原工作区一起带出来的：它们测的是同工作区里的另一个
noul-triage 功能，import 它的 `muiltilab` 包。`npm run test:py` 因此只跑 gate
自己的三个测试文件；要跑全套，需要在能 import triage 包的检出里进行。

---

## 验证记录

**2026-09-21（跨会话 + 第二轮标定）**

- 跨会话：插件在全新会话中自然产生 45+ 条决策，session_id/model 记录正确，
  allow/ask/deny 三路符合预期，p50 约 830ms。跨会话稳定性确认。
- 第二轮标定（37 条全新命令）：destructive 与 secret 类高危命令全部正确 deny，
  常规构建全 allow；`analyze.py --sweep` 显示五个阈值全部位于平坦区，无需调整。
- **路径豁免补丁**：destructive 的 deny 在"所有写目标都落在豁免前缀内"时降级
  为 ask——agent 不会被永久锁死在自家临时文件上，但人仍看得到这条命令。
  `secret_exposure` 永不降级；有一个目标在前缀外就整条不豁免；解析器对一切
  不认识的情况 fail closed（`cd` 进目录再删、`find -delete`、`xargs rm`、
  symlink 逃逸，全部维持原判）。实现：`hooks/exempt.py`（纯函数）与
  `src/index.ts` 同逻辑镜像，由 `tests/test_exempt.py`（34 例）和 `parity.ts`
  离线段共用同一张期望表约束——两侧不可能悄悄漂移。

**2026-10-08（302 条真实决策全量复盘）**

- 五个阈值全部维持默认，依据见上文「调阈值 → 2026-10-08 全量复盘」。
- 裁判健康：3 次 abort 全部 fail-open 放行并记录，无形状错误。
- near-miss 放行 25 条经逐条复查全部是读操作，无误放。

**2026-10-09（区域封锁排障：HTTP 451 → 代理打通）**

- 现象：desktop profile 装好并启用后，日志新增行全部是
  `err=Error: Error: 451 Unavailable For Legal Reasons`，无 `action`/`rule`。
  duration 稳定在 600ms 左右。
- 定位：应用外直连 `api.typesafe.ai` 同样 451，排除插件与 key；600ms 返回而非
  超时，排除网络不通。结论是出口被区域封锁，服务端明确拒绝。
- 对策：1.2.0 增加代理支持（`typesafeProxy` 配置项 → `HTTP_PROXY`/`HTTPS_PROXY`
  环境变量 → 直连，undici `ProxyAgent`/`EnvHttpProxyAgent`，按 URL 缓存）。本机
  在 **profile 自己的 patch 行**里钉内网代理后恢复：日志出现
  `action=allow rule=read_only` 且 `err` 为空，duration 升到 ~1.4s（请求经代理）。
- 教训：**451 期间闸门形同不存在，但界面无任何提示**——命令照跑，只在日志里留
  error 行。所以 `node tools/observe.mjs` 的 “judge errors” 计数是必看项，不是
  可选项。
- 附带教训：依赖装上 ≠ 启用。bundle 选中那一步漏掉时同样静默，表象是日志不长。
