// Browser half of the dsh-decision-gate plugin: the judge configuration card.
//
// dsh renders no generic form from a settings schema, so this card is
// contributed through slots rather than declared as one. It is registered as a
// tab in the Built-in plugins settings section (`settings.plugins.tab`) and on
// the Plugins page's bundle detail (`plugins.bundle.config`).
//
// The card reads and writes the settings form the Host serves for the
// `decision-gate` profile entry (`ctx.configForms`), so every write is validated
// against the plugin's Config schema, revision-fenced, and persisted into the
// profile patch. The volatile fields the schema declares are the fields this
// card stages; environment variables and schema defaults still govern whatever
// the card leaves unset.
//
// The judge route fields are pickers over the Host's own model catalog
// (`ctx.remote.session.modelCatalog()`, the same source the app's model
// switcher reads), so choosing a provider or a model is a selection rather than
// typing an id. When the catalog cannot be read the fields fall back to text
// inputs — a picker that never blocks configuration.
//
// Controls come from the seeded `@deepseek-ai/dsh-client-ui-primitives`
// (Input, Button — token-styled atoms), the same ones the modsearch card uses,
// so the form renders in the app's design instead of bare browser controls.
//
// Hand-written in the lazy-CJS bundle protocol (window.__ModuleLoader__.load
// with a factory returning cordis-plugin exports), so there is no build step:
// the same zero-build stance as the host half.

window.__ModuleLoader__.load({
  id: 'dsh-decision-gate',
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;

    // Profile entry id of the host half; the settings namespace the form serves.
    var NS = 'decision-gate';
    var PACKAGE_NAME = 'dsh-decision-gate';

    var TEXT = {
      title: 'decision-gate 裁判配置',
      subtitle: 'PreToolUse 门禁的裁判模型与阈值。留空 = 跟随环境变量或内置默认。',
      intro: '每次 shell 调用执行前，裁判模型回答五个问题（只读/破坏/泄密/外部不可逆/日常开发），按阈值给出 允许/询问/拒绝 并写日志；裁判不可达一律放行。日常只调前两项。',
      provider: '裁判后端',
      providerDshLlm: 'dsh-llm（跟随 DSH 配置的模型源，无需密钥；每条命令都等裁判，宜配快模型）',
      providerTypesafe: 'typesafe（TypeSafe 校准端点，亚秒级，需要 TYPESAFE_API_KEY）',
      model: '裁判模型（留空跟随会话当前模型）',
      routeProvider: '钉死 provider（留空跟随会话当前路由）',
      routeModel: '钉死模型（留空 = 上面 provider 的默认）',
      followRoute: '（不钉，跟随会话当前路由）',
      followModel: '（不指定，随后端默认）',
      matcher: '管辖的工具名模式',
      logPath: '决策日志路径',
      typesafeKey: 'TypeSafe API Key（typesafe 裁判用）',
      typesafeKeyEnv: '密钥环境变量名（未配密钥时的候选）',
      typesafeProxy: 'typesafe 代理（区域封锁时用）',
      gate: '阈值（0–1，环境变量可在留空时兜底）',
      destructive: 'destructive',
      secretExposure: 'secretExposure',
      externalIrreversible: 'externalIrreversible',
      readOnly: 'readOnly',
      routineDev: 'routineDev',
      exemptPrefixes: '豁免前缀（逗号分隔）',
      save: '保存',
      saving: '保存中…',
      saved: '已保存',
      failed: '保存失败，请重试',
      discard: '放弃修改',
      advancedShow: '展开高级设置',
      advancedHide: '收起高级设置',
      loading: '加载中…',
      catalogLoading: '模型目录读取中…',
      unavailable: 'decision-gate 未在运行，配置不可用。',
      readOnly: '当前 profile 不支持写入配置。',
      gateHint: '门禁',
      judgeHint: '裁判',
    };

    // Token vocabulary, mirroring the app's own settings cards.
    var LABEL_SECONDARY = 'var(--dsw-alias-label-secondary, inherit)';
    var LABEL_TERTIARY = 'var(--dsw-alias-label-tertiary, rgba(127,127,127,0.8))';
    var BORDER = '1px solid var(--dsw-alias-border-l2, rgba(127,127,127,0.35))';
    var CONTROL = {
      appearance: 'none',
      font: 'inherit',
      fontSize: '13px',
      lineHeight: 1.5,
      width: '100%',
      boxSizing: 'border-box',
      border: BORDER,
      borderRadius: '8px',
      padding: '5px 10px',
      background: 'var(--dsw-alias-bg-layer-2, transparent)',
      color: LABEL_SECONDARY,
    };

    // The fields the card stages. `path` addresses the namespace section; a
    // threshold that is not a number in [0, 1] marks the card invalid; a
    // catalog field renders as a picker while the catalog is readable. The
    // two basic fields answer "which model judges"; everything else is
    // advanced and stays collapsed until asked for.
    var FIELDS = [
      {
        key: 'judgeProvider', path: ['judgeProvider'], kind: 'select', label: TEXT.provider, group: TEXT.judgeHint,
        hint: '谁来当裁判：typesafe 是校准概率、亚秒级（默认，需 API key）；dsh-llm 免密钥但每条命令都等裁判',
      },
      {
        key: 'model', path: ['model'], kind: 'model', label: TEXT.model, group: TEXT.judgeHint,
        hint: '只决定谁审核、不影响会话模型；它每次调用都跑，宜挑便宜快的——慢模型会让每条 shell 命令都等裁判',
      },
      {
        key: 'routeProvider', path: ['judgeRoute', 'provider'], kind: 'provider', label: TEXT.routeProvider, group: TEXT.judgeHint, advanced: true,
        hint: '把裁判固定到某个 provider，不跟随会话路由',
      },
      {
        key: 'routeModel', path: ['judgeRoute', 'model'], kind: 'modelOfProvider', label: TEXT.routeModel, group: TEXT.judgeHint, advanced: true,
        hint: '配合上一项彻底钉死裁判模型，如 claude-corp · haiku',
      },
      {
        key: 'matcher', path: ['matcher'], kind: 'text', label: TEXT.matcher, group: TEXT.gateHint, advanced: true,
        hint: '门禁管辖哪些工具，默认只管 shell 三类',
      },
      {
        key: 'logPath', path: ['logPath'], kind: 'text', label: TEXT.logPath, group: TEXT.gateHint, advanced: true,
        hint: '判定日志；调阈值前先看它，误杀漏放都在里面',
      },
      {
        key: 'typesafeApiKey', path: ['typesafeApiKey'], kind: 'secret', label: TEXT.typesafeKey, group: TEXT.judgeHint, advanced: true,
        hint: 'typesafe 裁判的密钥：表单内掩码编辑、凭证库保管、不回显；留空 = 保持已存值',
      },
      {
        key: 'typesafeApiKeyEnv', path: ['typesafeApiKeyEnv'], kind: 'text', label: TEXT.typesafeKeyEnv, group: TEXT.judgeHint, advanced: true,
        hint: '未配置密钥时读这个环境变量；Windows 用户环境是最后兜底',
      },
      {
        key: 'typesafeProxy', path: ['typesafeProxy'], kind: 'text', label: TEXT.typesafeProxy, group: TEXT.judgeHint, advanced: true,
        hint: 'TypeSafe 被区域封锁（HTTP 451）时走这个代理，如 http://proxy.example:8080；留空=读 HTTP_PROXY/HTTPS_PROXY，再否则直连',
      },
      {
        key: 'destructive', path: ['destructive'], kind: 'number', label: TEXT.destructive, group: TEXT.gateHint, advanced: true,
        hint: '≥此值→拒绝；写目标全在豁免前缀内时降级为询问',
      },
      {
        key: 'secretExposure', path: ['secretExposure'], kind: 'number', label: TEXT.secretExposure, group: TEXT.gateHint, advanced: true,
        hint: '≥此值→拒绝且永不降级，最硬的一条',
      },
      {
        key: 'externalIrreversible', path: ['externalIrreversible'], kind: 'number', label: TEXT.externalIrreversible, group: TEXT.gateHint, advanced: true,
        hint: '≥此值→询问（push、部署、动远程等）',
      },
      {
        key: 'readOnly', path: ['readOnly'], kind: 'number', label: TEXT.readOnly, group: TEXT.gateHint, advanced: true,
        hint: '≥此值→直接放行',
      },
      {
        key: 'routineDev', path: ['routineDev'], kind: 'number', label: TEXT.routineDev, group: TEXT.gateHint, advanced: true,
        hint: '≥此值→直接放行（测试、装依赖等日常操作）',
      },
      {
        key: 'exemptPrefixes', path: ['exemptPrefixes'], kind: 'list', label: TEXT.exemptPrefixes, group: TEXT.gateHint, advanced: true,
        hint: '写目标全在这些目录内时，破坏拒绝降级为询问——agent 不会卡死在自家临时文件',
      },
    ];

    function readPath(value, path) {
      var current = value;
      for (var index = 0; index < path.length; index += 1) {
        if (current === null || typeof current !== 'object') return undefined;
        current = current[path[index]];
      }
      return current;
    }

    function effectiveText(field, value) {
      var raw = readPath(value, field.path);
      if (raw === undefined || raw === null) return '';
      if (field.kind === 'list') return Array.isArray(raw) ? raw.join(', ') : String(raw);
      return String(raw);
    }

    // One draft resolved into the op a save performs. Empty text clears the
    // field so the environment variable or schema default governs it again.
    function planOp(field, draft) {
      var text = draft.trim();
      if (field.kind === 'number') {
        if (text === '') return { op: 'unset', path: field.path };
        var parsed = Number(text);
        if (!isFinite(parsed) || parsed < 0 || parsed > 1) return undefined;
        return { op: 'set', path: field.path, value: parsed };
      }
      if (field.kind === 'list') {
        if (text === '') return { op: 'unset', path: field.path };
        var parts = text.split(',').map((part) => part.trim()).filter((part) => part !== '');
        return { op: 'set', path: field.path, value: parts };
      }
      if (text === '') return { op: 'unset', path: field.path };
      return { op: 'set', path: field.path, value: text };
    }

    // Catalog projections: the provider list, and the model list — either of
    // one provider (pinned route) or of every provider (bare model override).
    function providerOptions(groups) {
      return groups.map((group) => ({ value: group.id, label: group.id }));
    }

    function modelOptions(groups, providerId) {
      var options = [];
      groups.forEach((group) => {
        if (providerId !== undefined && providerId !== '' && group.id !== providerId) return;
        (group.models || []).forEach((model) => {
          options.push({ value: model.id, label: providerId ? model.id : `${group.id} · ${model.id}` });
        });
      });
      return options;
    }

    // A value the catalog does not carry (a stale pin, or a hand-typed id)
    // still renders, so the select never hides the stored value.
    function withCurrent(options, current, currentLabel) {
      if (current === '') return options;
      if (options.some((option) => option.value === current)) return options;
      return [{ value: current, label: currentLabel || current }].concat(options);
    }

    function ConfigCard() {
      var react = require('react');
      var ui = exports.__ui;
      var remote = exports.__remote;
      var h = react.createElement;
      var scope = exports.__scope;

      var snapshot = scope.getSnapshot();
      var drafts = react.useState(() => {
        var seeded = {};
        FIELDS.forEach((field) => { seeded[field.key] = effectiveText(field, snapshot.value) });
        return seeded;
      });
      var draft = drafts[0];
      var setDraft = drafts[1];
      var status = react.useState(() => ({ saving: false, saved: false, failed: false }));
      var state = status[0];
      var setState = status[1];
      var catalog = react.useState(() => ({ groups: [], status: 'idle' }));
      var groups = catalog[0].groups;
      var catalogStatus = catalog[0].status;
      var setCatalog = catalog[1];
      var advancedToggle = react.useState(() => false);

      react.useEffect(() => scope.subscribe(() => {
        var next = scope.getSnapshot();
        var reseed = {};
        FIELDS.forEach((field) => { reseed[field.key] = effectiveText(field, next.value) });
        setDraft(reseed);
      }), []);

      // The Host's model catalog, the same source the app's switcher reads;
      // refreshed when the settings document changes so a newly added model
      // shows up without a page reload.
      react.useEffect(() => {
        var alive = true;
        var load = () => {
          // `remote.session` is injected, so reaching it cannot throw. The catalog
          // itself stays optional: a host without modelCatalog degrades to text
          // inputs rather than blocking configuration.
          var call = typeof remote.session.modelCatalog === 'function'
            ? remote.session.modelCatalog()
            : Promise.reject(new Error('no model catalog on this host'));
          call.then((response) => {
            if (!alive) return;
            setCatalog(response.ok
              ? { groups: response.value.groups || [], status: 'ready' }
              : { groups: [], status: 'error' });
          }).catch(() => {
            if (alive) setCatalog({ groups: [], status: 'error' });
          });
        };
        load();
        var off = remote.$on('settings/document-updated', load);
        return () => { alive = false; off(); };
      }, []);

      if (snapshot.status !== 'ready') {
        return h('div', { style: { fontSize: '13px', color: LABEL_TERTIARY, padding: '12px 0' } },
          snapshot.status === 'loading' ? TEXT.loading : TEXT.unavailable);
      }

      var invalid = false;
      var ops = [];
      FIELDS.forEach((field) => {
        var text = draft[field.key];
        if (text === undefined) text = effectiveText(field, snapshot.value);
        // A secret never rides a response, so its stored value cannot be
        // shown: a blank draft means "keep what is stored" and writes nothing.
        if (field.kind === 'secret' && text.trim() === '') return;
        if (text === effectiveText(field, snapshot.value)) return;
        var op = planOp(field, text);
        if (op === undefined) { invalid = true; return; }
        ops.push(op);
      });

      var save = () => {
        if (invalid || ops.length === 0) return;
        setState({ saving: true, saved: false, failed: false });
        scope.mutate(ops, snapshot.revision).then((accepted) => {
          setState({ saving: false, saved: accepted, failed: !accepted });
        });
      };

      var discard = () => {
        var reseed = {};
        FIELDS.forEach((field) => { reseed[field.key] = effectiveText(field, snapshot.value) });
        setDraft(reseed);
        setState({ saving: false, saved: false, failed: false });
      };

      var selectControl = (options, field) => h('select', {
        value: draft[field.key] === undefined ? effectiveText(field, snapshot.value) : draft[field.key],
        onChange: (event) => setDraft({ ...draft, [field.key]: event.target.value }),
        style: CONTROL,
      }, options.map((option) => h('option', { key: option.value, value: option.value }, option.label)));

      var textControl = (field) => {
        var text = draft[field.key];
        if (text === undefined) text = effectiveText(field, snapshot.value);
        var type = field.kind === 'number' ? 'number' : field.kind === 'secret' ? 'password' : 'text';
        return h(ui.Input, {
          type: type,
          step: field.kind === 'number' ? '0.01' : undefined,
          min: field.kind === 'number' ? '0' : undefined,
          max: field.kind === 'number' ? '1' : undefined,
          value: text,
          onChange: (event) => setDraft({ ...draft, [field.key]: event.target.value }),
          style: { fontSize: '13px' },
        });
      };

      // One field row: a secondary-colored caption over the control, split by
      // the same hairline the app's own settings cards use.
      var row = (field) => {
        var text = draft[field.key];
        if (text === undefined) text = effectiveText(field, snapshot.value);
        var fieldInvalid = planOp(field, text) === undefined;
        if (fieldInvalid) invalid = true;

        var control;
        if (field.kind === 'select') {
          control = selectControl([
            { value: 'dsh-llm', label: TEXT.providerDshLlm },
            { value: 'typesafe', label: TEXT.providerTypesafe },
          ], field);
        } else if (catalogStatus === 'ready' && field.kind === 'provider') {
          var routeProvider = draft.routeProvider === undefined ? effectiveText(FIELDS[2], snapshot.value) : draft.routeProvider;
          control = selectControl(withCurrent(
            [{ value: '', label: TEXT.followRoute }].concat(providerOptions(groups)),
            routeProvider), field);
        } else if (catalogStatus === 'ready' && field.kind === 'model') {
          control = selectControl(withCurrent(
            [{ value: '', label: TEXT.followModel }].concat(modelOptions(groups, undefined)),
            text, `${text}（不在目录中）`), field);
        } else if (catalogStatus === 'ready' && field.kind === 'modelOfProvider') {
          var pinned = draft.routeProvider === undefined ? effectiveText(FIELDS[2], snapshot.value) : draft.routeProvider;
          control = selectControl(withCurrent(
            [{ value: '', label: TEXT.followModel }].concat(modelOptions(groups, pinned)),
            text, `${text}（不在目录中）`), field);
        } else {
          control = textControl(field);
        }

        return h('div', {
          key: field.key,
          style: {
            display: 'flex',
            flexDirection: 'column',
            gap: '6px',
            padding: '12px 0',
            borderTop: BORDER,
          },
        },
          h('div', { style: { fontSize: '13px', color: LABEL_SECONDARY } }, field.label),
          control,
          field.hint
            ? h('div', { style: { fontSize: '12px', lineHeight: 1.6, color: LABEL_TERTIARY } }, field.hint)
            : null,
          fieldInvalid
            ? h('div', { style: { fontSize: '12px', color: LABEL_TERTIARY } }, '阈值必须是 0–1 的数字')
            : null);
      };

      var groups_ = [];
      var lastGroup = null;
      FIELDS.forEach((field) => {
        if (field.advanced && !advancedToggle[0]) return;
        if (field.group !== lastGroup) {
          lastGroup = field.group;
          groups_.push(h('div', {
            key: `group-${field.group}`,
            style: { fontSize: '12px', color: LABEL_TERTIARY, padding: '12px 0 0' },
          }, field.group));
        }
        groups_.push(row(field));
      });

      return h('div', { style: { maxWidth: '560px' } },
        h('p', { style: { fontSize: '13px', color: LABEL_SECONDARY, margin: '4px 0 8px' } }, TEXT.subtitle),
        h('p', { style: { fontSize: '12px', lineHeight: 1.7, color: LABEL_TERTIARY, margin: '0 0 8px' } }, TEXT.intro),
        snapshot.writable ? null
          : h('p', { style: { fontSize: '13px', color: LABEL_TERTIARY } }, TEXT.readOnly),
        catalogStatus === 'idle' || catalogStatus === 'loading'
          ? h('p', { style: { fontSize: '13px', color: LABEL_TERTIARY } }, TEXT.catalogLoading)
          : null,
        groups_,
        h('div', { style: { padding: '4px 0' } },
          h(ui.Button, {
            variant: 'ghost',
            size: 'sm',
            onClick: () => advancedToggle[1](!advancedToggle[0]),
          }, advancedToggle[0] ? TEXT.advancedHide : TEXT.advancedShow)),
        h('div', { style: { display: 'flex', gap: '8px', alignItems: 'center', padding: '16px 0 4px' } },
          h(ui.Button, {
            variant: 'primary',
            size: 'md',
            onClick: save,
            disabled: invalid || state.saving || ops.length === 0 || !snapshot.writable,
          }, state.saving ? TEXT.saving : TEXT.save),
          h(ui.Button, { variant: 'ghost', size: 'md', onClick: discard }, TEXT.discard),
          state.saved ? h('span', { role: 'status', style: { fontSize: '13px', color: LABEL_TERTIARY } }, TEXT.saved) : null,
          state.failed ? h('span', { role: 'status', style: { fontSize: '13px', color: LABEL_TERTIARY } }, TEXT.failed) : null));
    }

    function mountCard(ctx) {
      var react;
      var ui;
      try {
        react = require('react');
        ui = require('@deepseek-ai/dsh-client-ui-primitives');
      } catch (error) {
        // A card that cannot load must say so. Returning silently here is how
        // 0.4.0 shipped a settings page that simply was not there: one
        // console.error, no visible trace, and a README promising a form.
        console.error(`[decision-gate] settings card skipped: ${error}`);
        var reason = String(error && error.message ? error.message : error);
        var notice = function () {
          return react && react.createElement
            ? react.createElement('pre', { style: { padding: '12px', whiteSpace: 'pre-wrap' } },
                'decision-gate: the settings card could not load, so configuration '
                + 'happens only through this profile\'s cordis.patch.yml.\n\n'
                + reason)
            : null;
        };
        notice.displayName = 'DecisionGateCardError';
        notice.__decisionGateError = reason;
        exports.__cardError = reason;
        ctx.slots.inject('settings.plugins.tab', function* () {
          yield ctx.slots.register({
            name: 'settings.plugins.tab',
            id: 'decision-gate-config',
            order: 30,
            label: function () { return 'decision-gate（加载失败）' },
          }, notice);
        });
        ctx.slots.inject('plugins.bundle.config', function* () {
          yield ctx.slots.register({
            name: 'plugins.bundle.config',
            key: PACKAGE_NAME,
          }, notice);
        });
        return;
      }
      // The shared per-entry configuration form. The namespace is the profile
      // entry id the host half registers; while it is not served the snapshot
      // reports unavailable and the card renders nothing.
      var scope = ctx.configForms.get(NS);
      exports.__scope = scope;
      exports.__ui = ui;
      exports.__remote = ctx.remote;

      // slots.inject waits until a slot is declared, so each host fills the one
      // it has and the other wait never fires.
      ctx.slots.inject('settings.plugins.tab', function* () {
        yield ctx.slots.register({
          name: 'settings.plugins.tab',
          id: 'decision-gate-config',
          order: 30,
          label: () => TEXT.title,
        }, ConfigCard);
      });
      ctx.slots.inject('plugins.bundle.config', function* () {
        yield ctx.slots.register({
          name: 'plugins.bundle.config',
          key: PACKAGE_NAME,
        }, ConfigCard);
      });
    }

    function apply(ctx) {
      // These three are REQUIRED, declared at the top level like
      // dsh-liangshen's client does. Treating them as optional is what made the
      // card vanish without a trace: a scoped inject whose names do not all
      // resolve never fires its callback, so the card simply never mounted and
      // nothing reported it.
      mountCard(ctx);
    }

    exports.name = 'dsh-decision-gate-client';
    exports.inject = ['slots', 'configForms', 'remote', 'remote.session'];
    exports.apply = apply;
    return module.exports;
  },
});
