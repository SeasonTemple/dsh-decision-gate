# AGENT.md — 在这个仓库里干活的规矩

`dsh-decision-gate` 是 DSH 的 PreToolUse shell 门禁插件。人通过 README 使用它，你通过
这份文件改它。

**本文件只写规则和坑，不复制别处的内容。** 安装 / 配置 / 使用看 `README.md`（英文）
和 `README.zh.md`（中文）；部署细节与阈值标定记录看 `docs/decision-gate-setup.md`（英文）/ `docs/decision-gate-setup.zh.md`（中文）。
那份文档是唯一真源——这里只做指针，避免出现第二份会漂移的真相。

下面每一条都是**被违反过才写下来的**。不要靠人提醒，动手前先读完。

---

## 提交纪律

1. ** Conventional Commits，没有例外。** 格式 `<type>(<scope>): <subject>`：

   | type | 用于 |
   | --- | --- |
   | `feat` | 新功能（对外可见的能力变化） |
   | `fix` | 修 bug |
   | `docs` | 只改文档 |
   | `refactor` | 不改行为的重构 |
   | `test` | 只加/改测试 |
   | `chore` | 构建、打包、依赖、配置 |

   subject 用祈使句、小写开头、不加句号、控制在 ~72 字符内。
   例：`feat: PreToolUse decision gate with swappable judge backends`。

2. **提交信息必须分段写清楚，不许一句话糊弄。** 至少覆盖：做了什么、为什么
   （尤其是“为什么现在做”）、验证结果、破坏性变更。多个 `-m` 参数每个渲染成
   一段，比写成一长行好。**“initial commit”“update”“fix stuff” 这类是失职。**

3. **首次发布用单个 initial commit**，不要硬拆。源码 + 测试 + 文档 + 打包配置
   本来就是一个整体，拆分只会制造无意义的历史。规范体现在 message 结构上，
   不在提交数量上。

4. **一个提交只做一件事。** 改判定逻辑就别顺手改文档格式；改名就单独一个提交
   （本仓库 `1.3.0` 就是把“改名”和“许可证变更”分成两条 bullet 写在同一类
   Changed 下，因为它们同属一次身份变更）。

5. **提交前必须跑测试**，提交信息里写清跑了什么、结果如何。没跑过就不许提交。

6. **不许提交**：`runtime/`（决策日志，含真实命令与 session_id）、
   `lib/decisions.jsonl`、任何 `*.tgz`、`node_modules/`、`__pycache__/`。
   `.gitignore` 已经挡了这些，但 `git add -A` 之后**要核对 `git status --short`
   的清单**，出现意外条目就叫停。

7. **推送到公开仓库前必做敏感信息终检**（见下文「发布纪律」第 2 条）。公开仓库
   不可逆——历史里每一行都抹不掉。

---

## 代码规范

8. **TypeScript strict，不用 `any`。** 确实需要逃逸时用 `unknown` + 收窄，或
   `as` 并注释原因。`src/host.d.ts` 里的 `declare module` 是类型声明，不在此列。

9. **注释和文档用中文**（本仓库的既有风格），代码标识符用英文。注释解释“为什么”，
   不复述“做了什么”——代码本身已经说了后者。

10. **命名**：常量 `UPPER_SNAKE_CASE`，函数/变量 `camelCase`，类型/类
    `PascalCase`。插件对外的 id 用短横线（`decision-gate`），npm 包名带前缀
    （`dsh-decision-gate`）。

11. **运行时依赖是特权，不是便利。** 目前只有两个：`@deepseek-ai/schemastery`
    和 `undici`。加第三个之前先问：能不能用 Node 内置模块解决？门禁跑在每次
    shell 调用前，依赖越多启动越慢、面越大。

12. **fail-open 是契约，不是缺陷。** 任何新增的失败路径都必须：记录原因到日志
    → `next()` 放行。门禁绝不能反过来成为卡死 harness 的东西。改这块时
    `tests/functional.mjs` 的 fail-open 用例必须仍然通过。

---

## 文档纪律

13. **默认值有三处，必须一致**：`src/index.ts` 的 schema、`cordis.patch.yml`
    的 bundle 行、两篇 README 的配置表。改一处就要改全部。本仓库出过真实事故：
    README 表格写 `judgeProvider` 默认 `dsh-llm`，而代码是 `typesafe`。

14. **文档里引用的文件名/路径必须真实存在。** 改名前先全局搜一遍引用（含
    README、AGENT.md、CHANGELOG、docs、代码注释、hooks.json、package.json 的
    scripts）。漏一处的后果是门禁或测试静默失效。

15. **CHANGELOG 的历史条目不许改写。** 它们记录那个版本发布时的事实。发现历史
    写错了，在新条目里更正，不要回去改旧行。批量文本替换时**把 CHANGELOG 排除
    在外**，只手动加新条目。

16. **`cordis.patch.yml` 必须机器中立**，因为它随包分发。绝对路径、代理地址、
    API key 都属于部署本地值，放 profile 自己的 patch 行（按 id 覆盖）。

---

## 发布纪律（打包 / 推送前逐条过）

17. **版本号三处同步**：`package.json`、`dsh.plugin.json`、`CHANGELOG.md`。
    少一处就会出现两个不同内容的包共用一个版本号。

18. **敏感信息终检**，公开仓库前必跑：

    ```bash
    # 在仓库根目录，检查 git 会跟踪的文件（排除 node_modules / runtime / *.tgz）
    rg -n '10\.\d+\.\d+\.\d+|zhanghj40|sk-[A-Za-z0-9]{16,}|gho_[A-Za-z0-9]{20,}|C:\\Users\\' \
       --glob '!node_modules' --glob '!runtime' --glob '!*.tgz' --glob '!*.jsonl'
    ```

    要盯的五类：内网 IP、本地用户名、密钥形态、真实邮箱、绝对 home 路径。
    命中数为 0 才能推。作者身份用 GitHub 匿名邮箱
    （`<id>+<user>@users.noreply.github.com`），不要写真实邮箱。

19. **打包后核对清单**：

    ```bash
    pnpm pack --dry-run     # 发布前看文件清单
    tar -tzf dsh-decision-gate-*.tgz   # 打成包后复核
    ```

    必须只有：`lib/index.js`、`lib/index.d.ts`、`dsh/`、`docs/`、
    `cordis.patch.yml`、`dsh.plugin.json`、`LICENSE`、`package.json`、
    `README.md`、`README.zh.md`。出现 `lib/decisions.jsonl`（真实决策数据）
    或任何绝对路径就是事故。

20. **测试全绿才算完成**：

    ```bash
    node tests/functional.mjs   # 0 failures
    tsc -p tsconfig.json --noEmit
    node src/parity.ts          # 离线段 signal drift 必须为 0
    python -m pytest tests/test_decision_gate.py tests/test_exempt.py tests/test_analyze.py -q
    ```

    parity 的**实时重放段**需要 `TYPESAFE_API_KEY` 且网络可达（它用裸 `fetch`，
    不走代理）；区域封锁环境下那 26 个 mismatch 是 451 造成的，不是逻辑问题——
    看 `signal drift` 而不是 `decision mismatches`。

21. **LICENSE 与 `package.json` 的 `license` 字段必须一致**，两篇 README 的许可
    章节、CHANGELOG 条目同步更新。当前是 `BUSL-1.1`。

---

## 改判定逻辑

22. **有两份实现，必须同步改。** `hooks/*.py`（Python 孪生，参考实现 + 回归基线）
    与 `src/index.ts`（插件本体）逐字镜像。只改一边，`src/parity.ts` 会红。
    改完必跑：

    ```bash
    node src/parity.ts          # 26 条基线决策 + 30 例豁免 + 3 条降级规则
                                # + 12 例裁判输出解析 + 10 种配置形状
    node tests/functional.mjs   # 14 个 fake-context 用例（双后端、fail-open、日志）
    python -m pytest tests/test_decision_gate.py tests/test_exempt.py tests/test_analyze.py -q
    ```

    `tests/test_policy.py`、`tests/test_triage.py`、`tests/test_live_path.py`
    （以及 `examples/`）测的是同工作区的另一个功能，import `muiltilab` 包，
    **不属于本包**，别以为改坏了什么。

23. **阈值是标定结果，不是可调参数。** 五个阈值在 TypeSafe 校准过的 `noul` 概率
    标尺上定过两轮（2026-09-21），又经过 302 条真实决策的全量复盘（2026-10-08，
    结论：全部维持默认）。动任何一条之前先看数据：

    ```bash
    node tools/observe.mjs      # 决策分布、裁判错误率、near-miss 放行、近期拦截
    ```

    然后逐条问：翻转的是“误杀”还是“真危险”。**抬 `secret_exposure` 是明确禁止的**
    ——0.70 会放行 `env | grep -i key`（0.66）。**换 `dsh-llm` 后端等于作废全部
    标定**——它自报的概率不在阈值所依据的那把标尺上。

24. **matcher 必须带 `^(...)`。** DSH 对 claude-code dialect 会把纯
    `[A-Za-z0-9_|]+` 的 pattern 当字面量列表精确比较，`terminal_` 就永远匹配不上
    `terminal_open`。有专门测试守这点，别绕过它。

25. **不要扩大 matcher 去闸文件工具。** 文件沙箱已经从机制上管住了路径，越界直接
    拒绝；再套一层语义闸门既冗余又高摩擦——实测 `write` 新文件的 `routine_dev`
    只有 0.27，会导致每次改文件都弹确认。shell 才是需要语义判断的逃逸口。

26. **裁判请求预算 60s，别调小。** 通用会话模型（尤其是推理模型）需要几十秒，
    旧的 10s 预算会把每次这类调用掐成 fail-open，那和“闸门默许一切”无法区分。

---

## 环境注意

27. 工作区 `node_modules` 只装了运行时依赖。跑 `npm run typecheck` / `build` 前先
    `npm install`（typescript、@types/node 是 devDependencies）。
28. **编译后必须验证产物，不能只看出退码。** 今天一整天的“tsc 通过”是假的：
    `& tsc ... | Select-Object` 在 PowerShell 里根本不会执行外部脚本，而
    `$LASTEXITCODE` 为空被当成了 0，于是 `lib/index.js` 停在上一个构建数小时，中间
    所有测试结果都来自旧代码。**正确做法**：`& node <tsc.js 路径> -p tsconfig.json`
    直接跑，然后核对产物的 `LastWriteTime` 和内容（`Select-String` 找新符号），
    两者都对才叫编译过。

29. **测试必须用生产里真实失败的那个字符串，不是它的近似值。** 今天三个 bug 全是
    “测试全绿、真实不生效”，因为测试一直喂自己想象中输入框。直到用被拒调用的
    **原样命令**驱动插件，才第一次看到 `false`。看到一个失败输入时，把它逐字抄进
    测试，不要凭记忆重打。

30. **改动超过十行就先读后写、改完立即编译。** 今天用行号操作把 `src/index.ts`
    从 1178 行毁成 1 行，因为我在脑子里假设文件状态而没有核对。大改动前先读目标
    区域，改完立刻 `tsc` + 跑测试，不要攒着继续改。

31. **本文件不进包**：它是给改这个插件的人看的，装插件的人只需要 README。
28. `tests/functional.mjs` 要写 `runtime/`。如果所在会话的沙箱只给工作区根目录写
    权限，它会在开头的 `rmSync` 上 EPERM——那是环境限制，不是测试或代码的问题。

32. **本文件不进包**：它是给改这个插件的人看的，装插件的人只需要 README。

33. **`authorizedOperations` 是唯一的“免问”通道，别的地方不许开。** 它只把
    `external_irreversible` 的 ask 降级为 allow，按语句匹配。改这块时守住两条
    不变量：`secret_exposure` 和 `destructive` 的判定必须排在它前面（白名单洗不白
    任何东西），匹配必须是“拆语句 + 剥定位外壳”而非正则（正则白名单必然被写宽）。
    `src/index.ts` 的 `decide`、`hooks/policy.py` 的 `decide`、两边的
    `isAuthorized` / `is_authorized` 是同一逻辑的四份镜像，改一处就改四处，然后跑
    parity 的 `authorization:` 段和 functional 的第 11 组。
