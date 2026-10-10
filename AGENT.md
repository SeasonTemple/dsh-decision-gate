# AGENT.md — 在这个仓库里干活的规矩

`dsh-decision-gate` 是 DSH 的 PreToolUse shell 门禁插件。人通过 README 使用它，你通过
这份文件改它。

**本文件只写规则和坑，不复制别处的内容。** 安装 / 配置 / 使用看 `README.md`（英文）
和 `README.zh.md`（中文）；部署细节与阈值标定记录看 `docs/decision-gate-setup.md`。
那份文档是唯一真源——这里只做指针，避免出现第二份会漂移的真相。

---

## 改判定逻辑

1. **有两份实现，必须同步改。** `hooks/*.py`（Python 孪生，参考实现 + 回归基线）
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

2. **阈值是标定结果，不是可调参数。** 五个阈值在 TypeSafe 校准过的 `noul` 概率
   标尺上定过两轮（2026-09-21），又经过 302 条真实决策的全量复盘（2026-10-08，
   结论：全部维持默认）。动任何一条之前先看数据：

   ```bash
   node tools/observe.mjs      # 决策分布、裁判错误率、near-miss 放行、近期拦截
   ```

   然后逐条问：翻转的是"误杀"还是"真危险"。**抬 `secret_exposure` 是明确禁止的**
   ——0.70 会放行 `env | grep -i key`（0.66）。**换 `dsh-llm` 后端等于作废全部
   标定**——它自报的概率不在阈值所依据的那把标尺上。

3. **matcher 必须带 `^(...)`。** DSH 对 claude-code dialect 会把纯
   `[A-Za-z0-9_|]+` 的 pattern 当字面量列表精确比较，`terminal_` 就永远匹配不上
   `terminal_open`。有专门测试守这点，别绕过它。

4. **不要扩大 matcher 去闸文件工具。** 文件沙箱已经从机制上管住了路径，越界直接
   拒绝；再套一层语义闸门既冗余又高摩擦——实测 `write` 新文件的 `routine_dev`
   只有 0.27，会导致每次改文件都弹确认。shell 才是需要语义判断的逃逸口。

5. **fail-open 是契约，不是缺陷。** 裁判报错、超时、输出不合协议 → 记录原因后
   `next()` 放行。门禁绝不能反过来成为卡死 harness 的东西。裁判请求预算 60s
   （1.1.0 从 10s 提上来的），别调小。

## 改配置和默认值

6. **默认值有三处，必须一致**：`src/index.ts` 的 schema、`cordis.patch.yml` 的
   bundle 行、两篇 README 的配置表。改一处就要改全部——README 的表格曾经和代码
   不一致过（`judgeProvider` 默认值写成 `dsh-llm`），这类漂移是本仓库出过的
   真实缺陷。

7. **`cordis.patch.yml` 必须机器中立**：这个文件随包分发。部署本地值（比如绝对
   `logPath`）放 profile 自己的 `cordis.patch.yml`，按 id 覆盖 bundle 行。

8. **日志字段**：每行决策记 `judge` 与 `model`；`provider` 只在 `dsh-llm` 行写。
   写文档时别夸大。

## 打包 / 发布

9. **`files` 精确枚举**：`lib/index.js`、`lib/index.d.ts`、`dsh`、`docs`、
   `cordis.patch.yml`、`dsh.plugin.json`。曾经因为写了整个 `lib`，把
   `lib/decisions.jsonl`（真实决策数据：命令、session_id、cwd）打进了 tarball。
   打包前核对：

   ```bash
   pnpm pack --dry-run
   ```

10. **版本号三处同步**：`package.json`、`dsh.plugin.json`、`CHANGELOG.md`。

11. **装包即装门禁**：挂载行在包自己的 bundle patch 里，不要往 profile 的根
    Include 手写行。desktop profile 的 CLI 按其设计拒绝操作，走应用内插件页
    （添加插件 → 本地路径）。

12. 装完**必须重启**才生效，且插件加载失败是静默的。唯一确认方式是跑一条 shell
    命令看 `runtime/decisions.jsonl` 有没有长；想确认闸门真在工作，让它跑
    `psql -c 'DROP TABLE users'`，应被 deny。

## 环境注意

- 工作区 `node_modules` 只装了运行时依赖。跑 `npm run typecheck` / `build` 前先
  `npm install`（typescript、@types/node 是 devDependencies）。
- `tests/functional.mjs` 要写 `runtime/`。如果所在会话的沙箱只给工作区根目录写
  权限，它会在开头的 `rmSync` 上 EPERM——那是环境限制，不是测试或代码的问题。
- 本文件不进包：它是给改这个插件的人看的，装插件的人只需要 README。
