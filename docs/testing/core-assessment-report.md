# 核心评估与报告闭环验证

## 当前结论与边界

本文件记录 V2 核心子项目的可复现自动化验证。`tests/test_core_journey.py`
只使用真实公开 HTTP 路由和共享管理员 HTTP 页面，不直接查询数据库：

`配置 → 简版预览 → 联系方式与同意 → Session 在线报告 → PDF 路由 → 预约意向 → 后台线索/评估/预约可见`

同一测试还验证新 Session 不能读取报告/PDF，完成与预约幂等重试不新增可见
记录，无效同意不会出现在后台。PDF 成功分支只在应用适配器边界使用受控 PDF
字节，以便验证路由、Session、响应和后台关联；它不是原生 WeasyPrint/Pango
视觉证据。

生产主机、生产数据库、systemd 服务和 Nginx 均未在此阶段访问或修改。
浏览器四分支验收与原生 PDF 页面检查由主任务后续执行；在证据文件实际生成并
人工检查前，不得宣称阶段 4、视觉验收或生产上线完成。

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
这些数字只证明自动化范围，不替代下一节的浏览器与原生 PDF 证据。

## 自动化证据矩阵

| 产品规格 | 已有自动化证据 | 仍需人工/后续证据 |
| --- | --- | --- |
| 5 评估体验 | 6 步/22 项配置、四分支、刷新状态和键盘状态机单元/运行时测试；核心旅程使用真实 config/preview/complete 路由 | 四分支桌面、移动端、键盘和刷新浏览器矩阵；5 分钟实测 |
| 6 场景与服务 | 场景门槛、排序、保底、服务包/交付物/周期/预算/验收的确定性测试 | 内容运营子项目补全公开信息架构、案例和资源关联 |
| 7 ROI | Decimal 三档公式、有限开放区间、除零、快照计算依据与报告展示测试 | 浏览器可读性和最终视觉设计 |
| 8 报告/PDF | 同一不可变快照、Session 隔离、HTML/PDF 路由、失败可重试、PDF 适配器边界测试 | Ubuntu 原生 PDF 中文字形、分页、图表、预算、声明和无联系人字段的页面检查 |
| 9 联系与预约 | 必填/选填、手机号去重、幂等完成、Session 预约、上海日期、预约状态与后台可见性测试 | 工作人员真实跟进流程演练 |
| 10 隐私生命周期 | 明示同意、固定政策版本、365 天到期匿名化、已成交豁免、撤回/删除、非识别指标保留测试 | 阶段 7 仅在备份和恢复演练后执行生产保留清理 |
| 14 埋点 | 11 个事件白名单、每事件固定字段、无 PII、Session 哈希、关键事件原子/幂等测试 | 浏览器弱网/离开页面的最佳努力送达观察；指标看板属于后续运营子项目 |
| 15 技术边界 | Flask/SQLite 单体、纯规则模块、CSRF、限流、通用错误、事务和幂等测试 | Ubuntu 运行库、systemd/Gunicorn/Nginx 阶段 7 预检 |
| 16 验收 | 全量 pytest、Node 语法/运行时测试和本文件的 HTTP 核心旅程 | 四分支浏览器矩阵全部通过后，核心闭环才具备进入视觉重设计的完整证据 |

## 浏览器与 PDF 证据（待主任务执行）

以下文件尚不能由本代码/文档步骤创建，也不得用占位图代替：

- `docs/testing/evidence/core-manufacturing-desktop.png`
- `docs/testing/evidence/core-retail-mobile.png`
- `docs/testing/evidence/core-professional-keyboard.png`
- `docs/testing/evidence/core-software-refresh.png`
- `docs/testing/evidence/core-report-page-1.png`

验收矩阵必须使用一次性数据库和测试专用隐私配置：制造业 1440×900 完成全链路；
零售 390×844 检查无横向溢出和粘性按钮遮挡；知识型专业服务仅键盘完成并检查
错误焦点/可见焦点；软件与创意服务在第 4 步刷新恢复、返回修改并确认
`sessionStorage` 从未出现联系方式；最后用原生 WeasyPrint 生成 PDF、渲染为页图
并检查中文字形、分页、分数表、推荐、预算、声明和联系人字段缺失。

任何一项失败都保持 Task 14 和阶段 4 为打开状态。

## 明确留给第二子项目的范围

产品规格第 4 节、6.3 的完整运营发布能力以及第 11—13 节中以下工作不在本核心
子项目内冒充完成：完整首页/行业/场景/服务/案例/资源信息架构；场景、服务包、
交付物、案例和资源的运营上下架；规则复制、预览和发布后台；旧内容逐项
保留/清洗/删除清单；资产模块和旧表在生产备份后的移除；指标看板与 CSV 导出。

现有最小后台只支持共享账号下的线索、跟进、预约和隐私请求闭环。最终设计系统、
响应式视觉、动效、SEO、性能和视觉回归属于第三子项目。
