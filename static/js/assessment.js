(function () {
  "use strict";

  const STEPS = ["profile", "pain", "value_process", "data_systems", "org_delivery", "roi"];
  const STORAGE_KEY = "assessment-v2-state";
  const ATTRIBUTION_LIMIT = 100;
  const ATTRIBUTION_KEYS = ["utm_source", "utm_medium", "utm_campaign"];
  const UUID_V4_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const UNICODE_DECIMAL_DIGIT_PATTERN = /\p{Decimal_Number}/gu;
  const CONTACT_EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  const MAINLAND_MOBILE_PATTERN = /^1[3-9]\d{9}$/;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  const BRANCH_OPTIONS = [
    { code: "manufacturing", label: "制造业", help: "生产、质量、设备、供应链与销售服务" },
    { code: "retail", label: "零售电商", help: "商品、门店、供应链、营销与客户服务" },
    { code: "professional_knowledge", label: "知识型专业服务", help: "咨询、财税、法务与人力资源" },
    { code: "software_creative", label: "软件与创意服务", help: "软件、设计、广告与营销服务" },
  ];

  const STEP_COPY = {
    profile: ["了解企业画像", "选择最接近您当前情况的行业、细分方向、部门和规模。"],
    pain: ["聚焦当前痛点", "请选择 1—3 个最希望优先改善的问题。"],
    value_process: ["业务价值与流程基础", "评估问题影响和当前流程的稳定程度。"],
    data_systems: ["数据与系统基础", "了解数据可用性、质量和现有工具基础。"],
    org_delivery: ["组织准备与落地条件", "确认负责人、团队意愿、预算和时间安排。"],
    roi: ["ROI 区间", "使用区间选项估算当前成本和可接受投入。"],
  };

  const DIMENSION_LABELS = {
    business_value: "业务价值",
    process: "流程基础",
    data: "数据基础",
    systems: "系统基础",
    organization: "组织准备",
    delivery: "落地条件",
  };

  const MATURITY_LABELS = {
    explore: "探索起步",
    pilot: "单点试验",
    scale: "规模扩展",
    collaborate: "智能协同",
  };

  const ROI_GROUP_LABELS = {
    headcount: "参与人数",
    monthly_hours: "每人每月耗时",
    monthly_cost: "人均月综合成本",
    loss_factor: "返工或损耗程度",
    budget: "可接受投入",
  };

  const ROI_OPTION_LABELS = {
    "1_5": "1—5 人",
    "6_20": "6—20 人",
    "21_50": "21—50 人",
    "50_plus": "50 人以上",
    under_20: "20 小时内",
    "20_80": "20—80 小时",
    "80_160": "80—160 小时",
    "160_plus": "160 小时以上",
    under_8000: "8000 元内",
    "8000_15000": "0.8—1.5 万元",
    "15000_30000": "1.5—3 万元",
    "30000_plus": "3 万元以上",
    rare: "很少",
    normal: "一般",
    high: "较高",
    severe: "严重",
    under_50000: "5 万元内",
    "50000_200000": "5—20 万元",
    "200000_500000": "20—50 万元",
    "500000_plus": "50 万元以上",
  };

  const QUESTION_DIMENSIONS = {
    value_process: new Set(["business_value", "process"]),
    data_systems: new Set(["data", "systems"]),
    org_delivery: new Set(["organization", "delivery"]),
  };

  const root = document.getElementById("assessment-wizard");
  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      clearStoredStateAndRedirect: clearStoredStateAndRedirect,
      configurationResponseIsCurrent: configurationResponseIsCurrent,
      ensureConfigurationAvailable: ensureConfigurationAvailable,
      privacySafeAttribution: privacySafeAttribution,
      setMutableControlsBusy: setMutableControlsBusy,
      validateContactValues: validateContactValues,
    };
  }
  if (!root) return;

  const stepTarget = document.getElementById("assessment-step");
  const contactGate = document.getElementById("assessment-contact-gate");
  const form = document.getElementById("assessment-form");
  const progress = document.getElementById("assessment-progress");
  const progressText = document.getElementById("assessment-progress-text");
  const title = document.getElementById("assessment-title");
  const errorTarget = document.getElementById("assessment-error");
  const liveStatus = document.getElementById("assessment-live-status");
  const backButton = document.getElementById("assessment-back");
  const continueButton = document.getElementById("assessment-continue");

  const restoredState = readStoredState();
  const state = {
    step: restoredState ? restoredState.step : 0,
    branchCode: restoredState ? restoredState.branchCode : "",
    subbranchCode: restoredState ? restoredState.subbranchCode : "",
    departmentCode: restoredState ? restoredState.departmentCode : "",
    companySizeCode: restoredState ? restoredState.companySizeCode : "",
    painCodes: restoredState ? restoredState.painCodes : [],
    answers: restoredState ? restoredState.answers : {},
    roiChoices: restoredState ? restoredState.roiChoices : {},
    submissionKey: restoredState ? restoredState.submissionKey : createSubmissionKey(),
    attribution: restoredState ? restoredState.attribution : readAttributionFromQuery(),
  };

  let configuration = null;
  let contactGateVisible = false;
  let busyRequestCount = 0;
  let latestConfigurationRequest = 0;

  function createSubmissionKey() {
    return crypto.randomUUID();
  }

  function readAttributionFromQuery() {
    const params = new URLSearchParams(window.location.search);
    const values = {};
    ATTRIBUTION_KEYS.forEach(function (key) {
      values[key] = params.has(key)
        ? privacySafeAttribution(params.get(key))
        : "";
    });
    return values;
  }

  function readStoredState() {
    let value;
    try {
      value = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "null");
    } catch (error) {
      return null;
    }
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    if (!UUID_V4_PATTERN.test(value.submissionKey || "")) return null;
    if (!Number.isInteger(value.step) || value.step < 0 || value.step >= STEPS.length) return null;
    if (!BRANCH_OPTIONS.some(function (item) { return item.code === value.branchCode; }) && value.branchCode !== "") return null;
    if (!isPlainObject(value.answers) || !isPlainObject(value.roiChoices) || !isPlainObject(value.attribution)) return null;
    if (!Array.isArray(value.painCodes)) return null;

    const attribution = {};
    ATTRIBUTION_KEYS.forEach(function (key) {
      attribution[key] = typeof value.attribution[key] === "string"
        ? privacySafeAttribution(value.attribution[key])
        : "";
    });
    return {
      step: value.step,
      branchCode: stringValue(value.branchCode),
      subbranchCode: stringValue(value.subbranchCode),
      departmentCode: stringValue(value.departmentCode),
      companySizeCode: stringValue(value.companySizeCode),
      painCodes: value.painCodes.filter(isString),
      answers: stringMapping(value.answers),
      roiChoices: stringMapping(value.roiChoices),
      submissionKey: value.submissionKey,
      attribution: attribution,
    };
  }

  function storedStateSnapshot() {
    return {
      step: state.step,
      branchCode: state.branchCode,
      subbranchCode: state.subbranchCode,
      departmentCode: state.departmentCode,
      companySizeCode: state.companySizeCode,
      painCodes: state.painCodes.slice(),
      answers: Object.assign({}, state.answers),
      roiChoices: Object.assign({}, state.roiChoices),
      submissionKey: state.submissionKey,
      attribution: Object.assign({}, state.attribution),
    };
  }

  function privacySafeAttribution(value) {
    if (typeof value !== "string") return "";
    const normalized = value.normalize("NFKC").trim().slice(0, ATTRIBUTION_LIMIT);
    if (normalized.indexOf("@") !== -1) return "";
    const decimalDigits = normalized.match(UNICODE_DECIMAL_DIGIT_PATTERN) || [];
    if (decimalDigits.length >= 11) return "";
    return normalized;
  }

  function persistState() {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(storedStateSnapshot()));
    } catch (error) {
      announce("当前浏览器无法保存刷新恢复进度，请不要关闭本页。");
    }
  }

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function isString(value) {
    return typeof value === "string";
  }

  function stringValue(value) {
    return typeof value === "string" ? value : "";
  }

  function stringMapping(value) {
    const result = {};
    Object.keys(value).forEach(function (key) {
      if (typeof value[key] === "string") result[key] = value[key];
    });
    return result;
  }

  function createElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    if (typeof text === "string") element.textContent = text;
    return element;
  }

  function safeId(value) {
    return String(value).replace(/[^a-z0-9_-]/gi, "-");
  }

  function createChoiceGroup(options) {
    const fieldset = createElement("fieldset", "choice-group");
    const legend = createElement("legend", "", options.legend);
    fieldset.appendChild(legend);
    if (options.help) fieldset.appendChild(createElement("p", "choice-help", options.help));

    const grid = createElement("div", "choice-grid");
    options.items.forEach(function (item, index) {
      const input = document.createElement("input");
      const multi = Boolean(options.multi);
      input.type = multi ? "checkbox" : "radio";
      input.name = options.name;
      input.value = item.code;
      input.id = "choice-" + safeId(options.name) + "-" + safeId(item.code);
      input.checked = multi
        ? options.selected.indexOf(item.code) !== -1
        : options.selected === item.code;
      if (!multi && index === 0) input.required = true;

      const label = createElement("label", "choice-card");
      label.htmlFor = input.id;
      const copy = createElement("span", "choice-copy", item.label);
      if (item.help) copy.appendChild(createElement("small", "", item.help));
      label.appendChild(input);
      label.appendChild(copy);
      input.addEventListener("change", function () {
        options.onChange(item.code, input);
      });
      grid.appendChild(label);
    });
    fieldset.appendChild(grid);
    return fieldset;
  }

  function appendStepIntro(container, stepName) {
    const copy = STEP_COPY[stepName];
    const intro = createElement("div", "assessment-step__intro");
    intro.appendChild(createElement("h3", "", copy[0]));
    intro.appendChild(createElement("p", "", copy[1]));
    container.appendChild(intro);
  }

  function renderWizard() {
    contactGateVisible = false;
    contactGate.hidden = true;
    stepTarget.hidden = false;
    stepTarget.replaceChildren();
    const stepName = STEPS[state.step];
    appendStepIntro(stepTarget, stepName);

    if (stepName === "profile") renderProfileStep();
    if (stepName === "pain") renderPainStep();
    if (QUESTION_DIMENSIONS[stepName]) renderQuestionStep(stepName);
    if (stepName === "roi") renderRoiStep();

    updateNavigation();
    persistState();
  }

  function renderProfileStep() {
    stepTarget.appendChild(createChoiceGroup({
      legend: "所属行业",
      name: "branch-code",
      items: BRANCH_OPTIONS,
      selected: state.branchCode,
      multi: false,
      onChange: selectBranch,
    }));

    if (!state.branchCode) return;
    if (!configuration || configuration.branch.code !== state.branchCode) {
      stepTarget.appendChild(createElement("p", "loading-note", "正在加载该行业的评估选项…"));
      return;
    }

    stepTarget.appendChild(createChoiceGroup({
      legend: "细分分支",
      name: "subbranch-code",
      items: configuration.subbranches,
      selected: state.subbranchCode,
      multi: false,
      onChange: function (code) {
        state.subbranchCode = code;
        persistState();
      },
    }));
    stepTarget.appendChild(createChoiceGroup({
      legend: "主要评估部门",
      name: "department-code",
      items: configuration.departments,
      selected: state.departmentCode,
      multi: false,
      onChange: function (code) {
        state.departmentCode = code;
        persistState();
      },
    }));
    stepTarget.appendChild(createChoiceGroup({
      legend: "企业规模",
      name: "company-size-code",
      items: configuration.company_sizes,
      selected: state.companySizeCode,
      multi: false,
      onChange: function (code) {
        state.companySizeCode = code;
        persistState();
      },
    }));
  }

  function renderPainStep() {
    if (!configuration) return;
    const minimum = configuration.pain_selection.minimum;
    const maximum = configuration.pain_selection.maximum;
    stepTarget.appendChild(createChoiceGroup({
      legend: "当前最想改善的业务痛点",
      help: "请选择 " + minimum + "—" + maximum + " 项。",
      name: "pain-codes",
      items: configuration.pain_points,
      selected: state.painCodes,
      multi: true,
      onChange: function (code, input) {
        const selected = new Set(state.painCodes);
        if (input.checked && selected.size >= maximum) {
          input.checked = false;
          showError("最多选择 " + maximum + " 个痛点。", input);
          return;
        }
        if (input.checked) selected.add(code);
        else selected.delete(code);
        state.painCodes = Array.from(selected);
        clearError();
        persistState();
      },
    }));
  }

  function renderQuestionStep(stepName) {
    if (!configuration) return;
    const dimensions = QUESTION_DIMENSIONS[stepName];
    configuration.questions.filter(function (question) {
      return dimensions.has(question.dimension);
    }).forEach(function (question) {
      stepTarget.appendChild(createChoiceGroup({
        legend: question.prompt,
        name: "answer-" + question.code,
        items: question.options,
        selected: state.answers[question.code] || "",
        multi: false,
        onChange: function (code) {
          state.answers[question.code] = code;
          clearError();
          persistState();
        },
      }));
    });
  }

  function renderRoiStep() {
    if (!configuration) return;
    Object.keys(ROI_GROUP_LABELS).forEach(function (group) {
      const items = (configuration.roi_options[group] || []).map(function (code) {
        return { code: code, label: ROI_OPTION_LABELS[code] || code };
      });
      stepTarget.appendChild(createChoiceGroup({
        legend: ROI_GROUP_LABELS[group],
        name: "roi-" + group,
        items: items,
        selected: state.roiChoices[group] || "",
        multi: false,
        onChange: function (code) {
          state.roiChoices[group] = code;
          clearError();
          persistState();
        },
      }));
    });
  }

  async function selectBranch(code) {
    if (busyRequestCount > 0) return;
    if (code === state.branchCode && configuration) return;
    state.branchCode = code;
    state.subbranchCode = "";
    state.departmentCode = "";
    state.companySizeCode = "";
    state.painCodes = [];
    configuration = null;
    clearError();
    persistState();
    renderWizard();
    await fetchConfiguration(code);
  }

  async function fetchConfiguration(branchCode) {
    const requestId = latestConfigurationRequest + 1;
    latestConfigurationRequest = requestId;
    setBusy(true);
    try {
      const url = root.dataset.configBase + "/" + encodeURIComponent(branchCode);
      const result = await requestJson(url, { method: "GET" });
      if (!configurationResponseIsCurrent(
        requestId,
        latestConfigurationRequest,
        branchCode,
        state.branchCode
      )) return false;
      configuration = result;
      sanitizeStateForConfiguration();
      clearError();
      renderWizard();
      announce("行业评估选项已加载。");
      return true;
    } catch (error) {
      if (configurationResponseIsCurrent(
        requestId,
        latestConfigurationRequest,
        branchCode,
        state.branchCode
      )) {
        configuration = null;
        showError("评估选项暂时无法加载，您的进度已保留，请重试。", continueButton);
      }
      return false;
    } finally {
      setBusy(false);
    }
  }

  function configurationResponseIsCurrent(requestId, latestRequestId, requestedBranch, selectedBranch) {
    return requestId === latestRequestId && requestedBranch === selectedBranch;
  }

  async function ensureConfigurationAvailable(branchCode, currentConfiguration, loader) {
    if (currentConfiguration && currentConfiguration.branch.code === branchCode) {
      return true;
    }
    if (!branchCode) return false;
    return Boolean(await loader(branchCode));
  }

  function sanitizeStateForConfiguration() {
    if (!configuration) return;
    state.subbranchCode = allowedCode(configuration.subbranches, state.subbranchCode);
    state.departmentCode = allowedCode(configuration.departments, state.departmentCode);
    state.companySizeCode = allowedCode(configuration.company_sizes, state.companySizeCode);
    const painCodes = new Set(configuration.pain_points.map(function (item) { return item.code; }));
    state.painCodes = state.painCodes.filter(function (code) { return painCodes.has(code); }).slice(0, 3);

    const allowedAnswers = {};
    configuration.questions.forEach(function (question) {
      const selected = state.answers[question.code];
      if (question.options.some(function (item) { return item.code === selected; })) {
        allowedAnswers[question.code] = selected;
      }
    });
    state.answers = allowedAnswers;

    const allowedRoi = {};
    Object.keys(configuration.roi_options).forEach(function (group) {
      if (configuration.roi_options[group].indexOf(state.roiChoices[group]) !== -1) {
        allowedRoi[group] = state.roiChoices[group];
      }
    });
    state.roiChoices = allowedRoi;
  }

  function allowedCode(items, selected) {
    return items.some(function (item) { return item.code === selected; }) ? selected : "";
  }

  function validateCurrentStep() {
    const stepName = STEPS[state.step];
    if (stepName === "profile") {
      if (!state.branchCode) return validationIssue("请选择所属行业。", "branch-code");
      if (!configuration) return { message: "行业选项尚未加载，请重试。", target: continueButton, retryConfiguration: true };
      if (!state.subbranchCode) return validationIssue("请选择细分分支。", "subbranch-code");
      if (!state.departmentCode) return validationIssue("请选择主要评估部门。", "department-code");
      if (!state.companySizeCode) return validationIssue("请选择企业规模。", "company-size-code");
    }
    if (stepName === "pain") {
      const limits = configuration.pain_selection;
      if (state.painCodes.length < limits.minimum || state.painCodes.length > limits.maximum) {
        return validationIssue("请选择 1—3 个当前痛点。", "pain-codes");
      }
    }
    if (QUESTION_DIMENSIONS[stepName]) {
      const missingQuestion = configuration.questions.find(function (question) {
        return QUESTION_DIMENSIONS[stepName].has(question.dimension) && !state.answers[question.code];
      });
      if (missingQuestion) return validationIssue("请回答当前页面的全部问题。", "answer-" + missingQuestion.code);
    }
    if (stepName === "roi") {
      const missingGroup = Object.keys(ROI_GROUP_LABELS).find(function (group) {
        return !state.roiChoices[group];
      });
      if (missingGroup) return validationIssue("请选择当前页面的全部 ROI 区间。", "roi-" + missingGroup);
    }
    return null;
  }

  function validationIssue(message, name) {
    return {
      message: message,
      target: stepTarget.querySelector('[name="' + name + '"]'),
    };
  }

  function buildAssessmentPayload() {
    return {
      schema_version: "2.0",
      profile: {
        branch_code: state.branchCode,
        subbranch_code: state.subbranchCode,
        department_code: state.departmentCode,
        company_size_code: state.companySizeCode,
        pain_codes: state.painCodes.slice(),
      },
      answers: Object.assign({}, state.answers),
      roi_choices: Object.assign({}, state.roiChoices),
    };
  }

  async function handleContinue() {
    if (busyRequestCount > 0) return;
    clearError();
    if (contactGateVisible) {
      await requestCompletion();
      return;
    }

    if (!state.branchCode && state.step > 0) {
      state.step = 0;
      renderWizard();
      showError("请重新选择所属行业。", stepTarget.querySelector('[name="branch-code"]'));
      return;
    }
    if (state.branchCode) {
      const ready = await ensureConfigurationAvailable(
        state.branchCode,
        configuration,
        fetchConfiguration
      );
      if (!ready) return;
    }

    const issue = validateCurrentStep();
    if (issue) {
      showError(issue.message, issue.target);
      if (issue.retryConfiguration && state.branchCode) await fetchConfiguration(state.branchCode);
      return;
    }
    if (state.step < STEPS.length - 1) {
      state.step += 1;
      renderWizard();
      focusCurrentStep();
      return;
    }
    await requestPreview();
  }

  function handleBack() {
    if (busyRequestCount > 0) return;
    clearError();
    if (contactGateVisible) {
      contactGateVisible = false;
      renderWizard();
      focusCurrentStep();
      return;
    }
    if (state.step > 0) {
      state.step -= 1;
      renderWizard();
      focusCurrentStep();
    }
  }

  async function requestPreview() {
    setBusy(true);
    announce("正在生成简版结果。");
    try {
      const result = await requestJson("/api/v2/assessment/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildAssessmentPayload()),
      });
      showContactGate(result);
      announce("简版结果已生成，请填写联系方式以解锁完整报告。");
    } catch (error) {
      showError("简版结果暂时无法生成，您的全部答案已保留，请重试。", continueButton);
    } finally {
      setBusy(false);
    }
  }

  function showContactGate(result) {
    contactGateVisible = true;
    stepTarget.hidden = true;
    contactGate.hidden = false;
    document.getElementById("preview-maturity").textContent = MATURITY_LABELS[result.maturity] || result.maturity;
    document.getElementById("preview-strongest").textContent = DIMENSION_LABELS[result.strongest] || result.strongest;
    document.getElementById("preview-weakest").textContent = DIMENSION_LABELS[result.weakest] || result.weakest;

    const privacy = configuration.privacy_disclosure;
    document.getElementById("privacy-summary").textContent = [
      privacy.processor_name + "将" + privacy.purpose,
      "必填信息：" + privacy.required_data_categories.join("、") + "；选填信息：" + privacy.optional_data_categories.join("、") + "。",
      privacy.retention,
      privacy.expiry_action,
      privacy.rights,
      "联系渠道：" + privacy.contact,
    ].join(" ");
    const policyLink = document.getElementById("privacy-policy-link");
    policyLink.href = privacy.policy_url;
    policyLink.textContent = "查看隐私政策";
    document.getElementById("privacy-consent").checked = false;
    updateNavigation();
    document.getElementById("contact-gate-title").focus();
  }

  async function requestCompletion() {
    const contact = validateContactValues({
      company_name: document.getElementById("company-name").value,
      contact_name: document.getElementById("contact-name").value,
      phone: document.getElementById("phone").value,
      email: document.getElementById("email").value,
      wechat: document.getElementById("wechat").value,
    });
    if (!contact.valid) {
      const invalidField = document.getElementById(contact.fieldId);
      showError(contact.message, invalidField);
      invalidField.focus();
      return;
    }
    const consentField = document.getElementById("privacy-consent");
    if (!consentField.checked) {
      showError("请阅读说明并勾选隐私与联系授权。", consentField);
      consentField.focus();
      return;
    }

    setBusy(true);
    announce("正在生成完整报告。");
    try {
      const result = await requestJson("/api/v2/assessment/complete", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": configuration.csrf_token,
        },
        body: JSON.stringify({
          submission_key: state.submissionKey,
          assessment: buildAssessmentPayload(),
          contact: contact.values,
          consent: {
            accepted: consentField.checked,
            policy_version: configuration.consent_policy_version,
          },
          attribution: {
            source: "website_assessment",
            utm_source: state.attribution.utm_source,
            utm_medium: state.attribution.utm_medium,
            utm_campaign: state.attribution.utm_campaign,
          },
        }),
      });
      if (typeof result.report_url !== "string" || !result.report_url.startsWith("/assessment/report/")) {
        throw new Error("invalid report destination");
      }
      clearStoredStateAndRedirect(
        window,
        STORAGE_KEY,
        result.report_url
      );
    } catch (error) {
      showError("完整报告暂时无法生成，您的答案和已填写信息仍保留在本页，请重试。", continueButton);
    } finally {
      setBusy(false);
    }
  }

  async function requestJson(url, options) {
    const response = await fetch(url, options);
    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      throw new Error("invalid server response");
    }
    if (!response.ok) throw new Error("request failed");
    return payload;
  }

  function clearStoredStateAndRedirect(browser, storageKey, reportUrl) {
    try {
      browser.sessionStorage.removeItem(storageKey);
    } catch (error) {
      // Storage cleanup is best-effort after the server has completed the flow.
    }
    browser.location.assign(reportUrl);
  }

  function validateContactValues(rawValues) {
    const values = {
      company_name: stringValue(rawValues.company_name).trim(),
      contact_name: stringValue(rawValues.contact_name).trim(),
      phone: stringValue(rawValues.phone).trim(),
      email: stringValue(rawValues.email).trim(),
      wechat: stringValue(rawValues.wechat).trim(),
    };
    if (!values.company_name) return invalidContact("company-name", "请输入企业名称。");
    if (values.company_name.length > 200) return invalidContact("company-name", "企业名称不能超过 200 个字符。");
    if (!values.contact_name) return invalidContact("contact-name", "请输入联系人。");
    if (values.contact_name.length > 100) return invalidContact("contact-name", "联系人不能超过 100 个字符。");
    if (!validMainlandMobile(values.phone)) return invalidContact("phone", "请输入有效的中国大陆手机号。");
    if (values.email.length > 254 || (values.email && !CONTACT_EMAIL_PATTERN.test(values.email))) {
      return invalidContact("email", "请输入包含完整域名的有效邮箱，或将邮箱留空。");
    }
    if (values.wechat.length > 64) return invalidContact("wechat", "微信号不能超过 64 个字符。");
    return { valid: true, fieldId: "", message: "", values: values };
  }

  function validMainlandMobile(value) {
    let normalized = value.replace(/[\s-]/g, "");
    if (normalized.startsWith("+86")) normalized = normalized.slice(3);
    else if (normalized.startsWith("0086")) normalized = normalized.slice(4);
    return MAINLAND_MOBILE_PATTERN.test(normalized);
  }

  function invalidContact(fieldId, message) {
    return { valid: false, fieldId: fieldId, message: message, values: null };
  }

  function setBusy(isBusy) {
    busyRequestCount = Math.max(0, busyRequestCount + (isBusy ? 1 : -1));
    setMutableControlsBusy(root, busyRequestCount > 0);
  }

  function setMutableControlsBusy(container, isBusy) {
    container.setAttribute("aria-busy", String(isBusy));
    container.querySelectorAll("button, input, select, textarea").forEach(function (control) {
      control.disabled = isBusy;
    });
  }

  function updateNavigation() {
    const visibleStep = contactGateVisible ? STEPS.length : state.step + 1;
    progress.value = visibleStep;
    progress.textContent = visibleStep + " / " + STEPS.length;
    progressText.textContent = "第 " + visibleStep + " 步，共 " + STEPS.length + " 步";
    title.textContent = contactGateVisible ? "解锁完整评估报告" : STEP_COPY[STEPS[state.step]][0];
    backButton.hidden = state.step === 0 && !contactGateVisible;
    continueButton.textContent = contactGateVisible
      ? "提交并查看完整报告"
      : state.step === STEPS.length - 1
        ? "生成简版结果"
        : "继续";
  }

  function showError(message, target) {
    errorTarget.textContent = message;
    errorTarget.hidden = false;
    errorTarget.focus();
    if (target && typeof target.focus === "function") {
      target.setAttribute("aria-invalid", "true");
    }
    announce(message);
  }

  function clearError() {
    errorTarget.hidden = true;
    errorTarget.textContent = "";
    root.querySelectorAll('[aria-invalid="true"]').forEach(function (element) {
      element.removeAttribute("aria-invalid");
    });
  }

  function announce(message) {
    liveStatus.textContent = "";
    window.setTimeout(function () {
      liveStatus.textContent = message;
    }, 20);
  }

  function focusCurrentStep() {
    const heading = stepTarget.querySelector("h3");
    if (!heading) return;
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
    heading.scrollIntoView({
      behavior: reducedMotion.matches ? "auto" : "smooth",
      block: "start",
    });
  }

  continueButton.addEventListener("click", handleContinue);
  backButton.addEventListener("click", handleBack);
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    handleContinue();
  });
  form.addEventListener("input", function (event) {
    if (event.target.matches("input")) event.target.removeAttribute("aria-invalid");
  });

  renderWizard();
  if (state.branchCode) fetchConfiguration(state.branchCode);
})();
