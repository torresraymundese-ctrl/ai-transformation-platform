# 后台展示最终收尾验收（2026-09-08）

## 范围与边界

基线为 `8c651700ced32825ae5363d7e47b53898933c625`，工作分支为 `codex/ai-platform-2.0-core`。

本次收尾仅包括后台评估列表的历史结果/关联线索展示、中文显示标签、列表与工作台布局，以及不稳定测试的固定夹具。匿名化、失联线索不回退旧个人信息；历史报告名称优先采用保存时的快照，不重新评分、匹配或计算 ROI。原始筛选和提交值保持不变。

已验收的公开报告、PDF、公共页面模板与 CSS/JS、评分/匹配/ROI、生产发布校验均未更改。未访问或改动工作树的 `data/`，未部署、迁移真实数据或执行物理打印。原有 `README.md` 和 `docs/testing/core-assessment-report.md` 修改不纳入本次提交。

## 4 项间歇失败的根因与修复

旧测试辅助函数按自增 ID 选择第一条场景。种子装载经过集合迭代，顺序随 Python 哈希种子变化；`PYTHONHASHSEED=6` 时选到 `data_process_foundation`，该兜底场景本来就不满足公开发布条件，服务正确返回 `scenario_public_incomplete` / HTTP 400。

固定种子后，旧夹具精确复现 **4 failed、15 passed**。修复只让成功路径测试按 `scenario` 类型与 `mfg-knowledge-assistant` 稳定公开路径选取完整场景，不修改应用或种子装载逻辑，不放宽发布门槛。独立测试仍断言兜底场景不可发布。

修复过程中曾误用不存在的 `content_groups.group_key`，导致测试查询失败；随后按实际 schema 改为已有的 `canonical_slug`。该中间失败不计为通过，最终验证均针对修正后的夹具。

## 自动验证

- 固定故障种子 `6`：`tests/test_catalog_content_admin.py` 与 `tests/test_content_journey.py`，**27 passed in 21.96s**。
- 哈希种子 `0..9`：原来失败的排期、审核发布、无标题正文、空白标题正文 4 项，在每个独立 Python 进程中全部通过，合计 **40 次通过**。
- 所有 8 个 `tests/js/*.test.js`：**50 passed、0 failed、0 skipped，447.9485ms**。
- `python -m pip check`：`No broken requirements found.`
- 独立只读复核：无 Critical、Important 或 Minor 问题；确认夹具修复未掩盖兜底场景负向覆盖。
- 最新整仓回归：`python -m pytest -q --tb=short -p no:cacheprovider --basetemp=<全新 ASCII 临时路径>`，**2,241 passed in 1381.03s（23:01），exit 0**。这是针对本次最终代码的完整运行，没有失败、跳过或警告汇总；不以此前的 2,210 项结果替代。

完整运行使用既有虚拟环境、`PYTHONHASHSEED=6`、原 Windows 编码环境、进程级 WeasyPrint DLL 路径、全新 ASCII 临时 basetemp 和 `-p no:cacheprovider`，不使用生产数据库。

本地原始全量日志保留于 `.superpowers/sdd/2026-09-07-admin-experience-performance-closeout/final-current-seed6-pytest.log`（忽略的验收工作目录）。`git diff --check` 通过，报告与发布规则保护路径无差异。

## 浏览器证据与未验证项

已完成的前一轮后台展示验收：1440px 工作台卡片等高且同排按钮对齐；评估表格铺满容器，企业/测试邮箱/历史场景与服务名称可见；320/390px 页面无横向溢出，宽表格仅在具名可聚焦容器内滚动；键盘 Tab 可进入容器，Right 实际滚动表格。临时视口已恢复。

本轮复查沿用 `http://127.0.0.1:62851/admin` 的隔离测试预览，未重建或重新播种预览数据。页面正常可访问。

以下仍是明确验收缺口，而不是已完成项：

- 原生浏览器 200% 缩放：当前控制入口未成功执行缩放快捷键，未采用视口替代证据。
- 通用 HTTP 400 错误页的浏览器真实渲染与焦点：此前浏览器未显示该响应正文；当前预览没有可编辑的规则草稿，未为了补证新建业务记录。HTTP/脚本契约测试不等于视觉验收。
- 真机手机、实际 A4 打印；后者需可用设备与明确打印批准。
- 生产部署、真实数据校验/迁移、生产性能与监控：需指定目标环境、访问授权、备份回滚方案及验收负责人。

分支合并或推送/PR 需用户选择；本地通过不代表已上线。
