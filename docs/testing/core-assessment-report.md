# 核心评估与报告闭环验证

## 当前结论与边界

本文件记录 V2 核心子项目的可复现自动化验证。`tests/test_core_journey.py`
只使用真实公开 HTTP 路由和共享管理员 HTTP 页面，不直接查询数据库：

`配置 → 简版预览 → 联系方式与同意 → Session 在线报告 → PDF 路由 → 预约意向 → 后台线索/评估/预约可见`

同一测试还验证新 Session 不能读取报告/PDF，完成与预约幂等重试不新增可见
记录，无效同意不会出现在后台。PDF 成功分支只在应用适配器边界使用受控 PDF
字节，以便验证路由、Session、响应和后台关联；它不是原生 WeasyPrint/Pango
视觉证据。

生产主机、生产数据库、systemd 服务和 Nginx 均未在此阶段访问或修改。下文的
浏览器四分支验收与原生 PDF 页面检查使用一次性本地数据库和测试专用配置；它们
证明核心功能闭环，但不代表最终视觉重设计或生产上线完成。

## Windows 复现

从项目根目录运行：

```powershell
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe -m pytest tests\test_core_journey.py -q
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe app.py
```

最终静态与依赖检查：

```powershell
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m py_compile app.py security.py assessment_repository.py lead_repository.py appointment_repository.py assessment_completion_service.py
node --check static/js/assessment.js
git diff --check
.venv\Scripts\python.exe -m pytest -q
```

测试使用临时数据库和测试专用的隐私/管理员配置，不需要生产凭据。手工启动应用
前必须设置 README 列出的三个隐私变量和三个管理员安全变量；应用不会回退到
源码内置管理员密码或虚构的隐私处理者。

本次代码/文档提交前的实测结果：核心旅程 `2 passed in 3.10s`；核心旅程与
API、报告、预约、线索、管理员相关分区 `202 passed in 118.18s`；全量 Python
`465 passed in 215.96s`；三个 Node 运行时文件合计 `12 passed, 0 failed`。
这些数字只证明自动化范围；浏览器与原生 PDF 证据另列如下。

## 自动化证据矩阵

| 产品规格 | 已有自动化证据 | 仍需人工/后续证据 |
| --- | --- | --- |
| 5 评估体验 | 6 步/22 项配置、四分支、刷新状态、可见焦点与核心真实 HTTP 旅程；四分支浏览器矩阵见下文 | 5 分钟用户计时抽样 |
| 6 场景与服务 | 场景门槛、排序、保底、服务包/交付物/周期/预算/验收的确定性测试 | 内容运营子项目补全公开信息架构、案例和资源关联 |
| 7 ROI | Decimal 三档公式、有限开放区间、除零、快照计算依据与报告展示测试 | 浏览器可读性和最终视觉设计 |
| 8 报告/PDF | 同一不可变快照、Session 隔离、HTML/PDF 路由、失败可重试；Windows 原生 WeasyPrint/Pango 生成并检查 4 页 PDF | 阶段 7 Ubuntu 原生运行库复验 |
| 9 联系与预约 | 必填/选填、手机号去重、幂等完成、Session 预约、上海日期、预约状态与后台可见性测试 | 工作人员真实跟进流程演练 |
| 10 隐私生命周期 | 明示同意、固定政策版本、365 天到期匿名化、已成交豁免、撤回/删除、非识别指标保留测试 | 阶段 7 仅在备份和恢复演练后执行生产保留清理 |
| 14 埋点 | 11 个事件白名单、每事件固定字段、无 PII、Session 哈希、关键事件原子/幂等测试 | 浏览器弱网/离开页面的最佳努力送达观察；指标看板属于后续运营子项目 |
| 15 技术边界 | Flask/SQLite 单体、纯规则模块、CSRF、限流、通用错误、事务和幂等测试 | Ubuntu 运行库、systemd/Gunicorn/Nginx 阶段 7 预检 |
| 16 验收 | 全量 pytest、Node 语法/运行时、HTTP 核心旅程、四分支浏览器矩阵和原生 PDF 页图 | 阶段 7 生产候选复验与上线审批 |

## 浏览器与 PDF 证据

2026-08-21 使用一次性 SQLite 数据库、测试管理员和测试隐私配置完成以下验收；
所有联系方式均为本地虚构测试值，未连接生产：

- [制造业桌面完整报告](evidence/core-manufacturing-desktop.png)：1440×900 完成六步、简版结果、联系方式与同意、完整报告、原生 PDF 下载和预约提交。
- [零售电商手机视口](evidence/core-retail-mobile.png)：390×844 的七个页面状态均无横向溢出；结果联系页操作区与最后字段的重叠值为 0。
- [知识型专业服务键盘焦点](evidence/core-professional-keyboard.png)：必填错误通用且不回显输入；Tab/Shift+Tab 后单选项有 2.4px 可见焦点，返回第 3 步修改后可继续到结果页。
- [软件与创意服务刷新恢复](evidence/core-software-refresh.png)：第 4 步刷新后仍停留第 4 步，返回第 3 步修改答案后再次进入第 4 步。
- [原生 PDF 第 1 页](evidence/core-report-page-1.png)：WeasyPrint 69.0 + Pango 1.58.2 生成 4 页 PDF；逐页检查中文字形、分页、图表、ROI、服务包、风险和声明。

真实 PDF 首轮页面检查发现 WeasyPrint 忽略 HTML CSS 中的 SVG `fill`/`stroke`
属性并把雷达网格画成黑色；失败测试锁定后改为 SVG 显式呈现属性，并将左右标签
向图内收，重新生成的 4 页 PDF 已通过逐页检查。在线报告与 PDF 均未包含企业名、
联系人、手机号、邮箱或微信。

浏览器安全边界不直接读取 Session 存储；联系方式不进入 `sessionStorage` 由
`test_storage_snapshot_is_non_contact_and_restores_one_submission_key` 的持久化字段
白名单验证，浏览器只验证刷新恢复与返回修改行为。阶段 7 仍需在 Ubuntu 生产
候选环境复跑原生 PDF 和全部运行时门禁。

## 明确留给第二子项目的范围

产品规格第 4 节、6.3 的完整运营发布能力以及第 11—13 节中以下工作不在本核心
子项目内冒充完成：完整首页/行业/场景/服务/案例/资源信息架构；场景、服务包、
交付物、案例和资源的运营上下架；规则复制、预览和发布后台；旧内容逐项
保留/清洗/删除清单；资产模块和旧表在生产备份后的移除；指标看板与 CSV 导出。

现有最小后台只支持共享账号下的线索、跟进、预约和隐私请求闭环。最终设计系统、
响应式视觉、动效、SEO、性能和视觉回归属于第三子项目。

## 旧内容审阅清单（5A）

在已经执行 `python manage.py migrate` 的本地副本中运行：

```powershell
python manage.py inventory-content --format jsonl
python manage.py inventory-content --format jsonl --record
```

默认命令是零写入 dry-run，只读取旧 `services`、`cases`、`articles` 和
`announcements`，逐行输出确定性的 JSONL 审阅项。`--record` 只在一个事务中
新增或更新 `legacy_content_reviews`；它不会请求网络、创建目标内容、发布内容、
修改或删除旧行。相同来源校验和会保留已有人工决定和来源检查；来源校验和变化时，
旧决定与旧检查保留为历史证据但不再匹配当前校验和，并写入 `review_stale_at`。

清单不读取线索、站点配置或密钥。来源 URL 只展示去掉认证信息、查询参数和片段的
规范化 scheme/IDNA host/path；完整规范化 URL 仅以 SHA-256 记录。来源可达性检查和
经人工批准后的草稿转换属于后续任务，本命令不会把迁移内容自动发布。
