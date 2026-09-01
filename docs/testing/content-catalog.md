# 内容目录发布闭环验证

## 当前结论与边界

本文件记录阶段 5A 的可复现验证。`tests/test_content_journey.py` 只通过公开
HTTP、共享管理员 HTTP 页面和真实 CLI 入口操作系统；文件内的静态守卫禁止直接
导入 repository、调用 SQLite 执行方法或嵌入 SQL 语句。测试夹具只创建一次性
SQLite 数据库、媒体目录和测试管理员 Session，来源检查只使用 mock transport。

本轮没有连接生产服务器、生产数据库、Nginx、systemd 或真实外网，也没有部署或
临时开放公网。五项浏览器验收同样只使用一次性本地数据。外部 Edge 原生
Tab/Shift+Tab/Enter/Space 证据已关闭纯键盘 P2 B；随后用户提供的 Edge 200% 菜单截图、
全页截图与同源 live metrics 也关闭了 zoom/reflow 门禁。最终 task-level review、
控制器 focused/static/final-full 均已通过，一次性 `127.0.0.1:5092` 已关闭；
Task 13 尚未开始，部署继续受全局上线门禁约束。
这里不代表最终视觉重设计或生产发布已经完成；阶段 7 仍受备份、恢复演练、候选
烟雾测试和明确上线批准约束。

## HTTP/管理员/CLI 旅程

| 旅程 | 通过公开表面验证的结果 |
| --- | --- |
| 目录发布生命周期 | 草稿公开 404；管理员发布；复制修订；未来排期保持旧修订；`publish-due-content` 到期替换；管理员归档后公开 404 |
| 冲突恢复 | 过期锁版本的排期 POST 返回可恢复 409，保留当前草稿、冲突提示和提交的上海时间 |
| 服务完整性 | 管理员表单保留固定成熟度选择；公开服务展示行业、部门、痛点、范围、非范围、交付物、步骤、前置条件、周期、预算、验收、支持、关联内容和价格免责声明 |
| 移动筛选 | 行业、部门、成熟度交集只返回精确场景；页面包含移动 viewport 和可访问筛选表单 |
| 案例/资源/媒体/关系 | 一次性 PNG/PDF 经管理员上传；经授权匿名案例展示中文核验标签、指标周期和图片；来源资源经 mock HTTPS 检查后展示来源与附件；服务只关联已发布目标；私有依据和联系方式不进入公开正文 |
| 公告有效期 | 当前公告在详情和首页可见，到 `valid_until` 精确边界后详情 404、首页隐藏 |
| 旧内容决策 | `inventory-content` 默认 dry-run 两次输出一致；`--record` 后 `check-content-sources` 在零真实网络下记录通用状态；从 CLI 输出发现 seed 旧服务，预览要求锁版本 merge approval，apply 只合并草稿，重复 apply 返回同一 target，随后才由管理员发布 |
| 兼容与退役入口 | 旧抓取 POST 固定 410 且不调用网络；`/services`、`/insights` 只重定向到服务器固定相对路径并丢弃 query；未映射旧文章 404 |

种子内容有一个已知且被正式发布门禁拒绝的缺口：13 个场景中 12 个可发布，
`data-process-foundation` 固定返回 `scenario_public_incomplete`。验证保留并断言这个
缺口，没有降低完整性规则或虚构公开内容。

## Windows 本地复现

先按 README 创建虚拟环境并设置测试/本地专用配置。不要把 `DB_PATH`、媒体目录或
任何环境变量指向生产副本。从项目根目录运行：

```powershell
.venv\Scripts\python.exe manage.py migrate

# 零写入库存预览；人工核对后才记录 review 行
.venv\Scripts\python.exe manage.py inventory-content
.venv\Scripts\python.exe manage.py inventory-content --record

# 会访问已记录来源；本地自动化测试必须使用 mock transport，禁止真实外网
.venv\Scripts\python.exe manage.py check-content-sources

# decision JSONL 必须先预览；只有人工核对 target/锁版本后才 apply
.venv\Scripts\python.exe manage.py migrate-legacy-content --decisions .\decisions.jsonl
.venv\Scripts\python.exe manage.py migrate-legacy-content --decisions .\decisions.jsonl --apply

.venv\Scripts\python.exe manage.py publish-due-content

# 媒体恢复默认 dry-run；--apply 只做安全状态迁移，不删除文件或数据库行
.venv\Scripts\python.exe manage.py recover-media-storage
.venv\Scripts\python.exe manage.py recover-media-storage --apply
```

`inventory-content` 默认只读；`migrate-legacy-content` 默认预览。转换保留全部旧行，
只创建或显式合并 V2 `draft`，从不自动发布；`delete_later` 只是阶段 7 人工标签。
`check-content-sources` 和 `--apply` 必须在已校验备份、人工复核和受控维护窗口内
运行。来源检查结果只输出通用 code，不输出 URL query、响应正文、联系方式或私有
依据。

本轮测试命令统一使用仓库外层固定 Python 3.12 虚拟环境、离线依赖层、
`-p no:cacheprovider` 和位于
`.superpowers/sdd/2026-08-24-content-catalog-publishing/test-tmp/` 下的唯一绝对
`--basetemp`。可复现相关分区为：

```powershell
.venv\Scripts\python.exe -m pytest tests/test_content_journey.py `
  tests/test_content_migrations.py tests/test_content_validation.py `
  tests/test_content_publishing.py tests/test_media_service.py `
  tests/test_media_http.py tests/test_content_seed.py `
  tests/test_catalog_content_admin.py tests/test_public_catalog.py `
  tests/test_public_services.py tests/test_verified_cases.py `
  tests/test_resources_announcements.py tests/test_source_url_checker.py `
  tests/test_content_migration_cli.py tests/test_content_navigation.py `
  -q -p no:cacheprovider --basetemp <唯一绝对临时目录>
```

## 自动化与迁移证据

- Task 12 开始前，控制器对 14 个既有相关文件运行：
  `992 passed in 413.28s (0:06:53)`。
- SQL-free 最终 journey：`8 passed in 6.58s`。
- 空库应用全部迁移，以及带 001–005 记录和哨兵数据的隔离副本升级/二次幂等
  应用：`2 passed in 0.20s`。两条路径最终都记录到
  `009_case_basis_types`，001–005 副本的核心目录计数与业务/旧内容哨兵保持不变。
- 文档和浏览器证据落盘后的冻结前精确 15 文件分区：
  `1000 passed in 441.94s (0:07:21)`，exit 0。此前的中间异常
  `3 failed, 997 passed` 仍保留；其后精确 439-test 前缀、catalog admin 全文件和
  本次同命令均通过，故三次未打印 code 的 400 未复现、根因仍为 `UNKNOWN`，不把
  一次绿色重跑改写成已定位修复。
- 最终冻结树的唯一 full suite 使用独立 ASCII 绝对 basetemp
  `C:\Users\zz\AppData\Local\Temp\task12-controller-final-full-045`、
  `-p no:cacheprovider` 和命令级离线依赖运行：`1653 passed in 779.80s
  (0:12:59)`，exit 0。没有沿用 Task 11 的 `1531 passed`。
- final-full 前静态门禁使用 Python 3.12.13 和命令级离线 `pypdf 6.10.0`：
  `pip check` 无损坏依赖；103 个跟踪/旅程 Python 文件通过 `py_compile`；两项
  `node --check` exit 0；四文件 Node 精确集 `21 passed`；`git diff --check`
  exit 0。历史 `compileall -q .` 对不可访问 pytest 临时目录产生的 `Can't list`
  警告不作为干净语法证据，已由精确 `py_compile` 取代。

## 浏览器证据

以下证据来自同一个一次性本地 SQLite/媒体环境和只绑定
`127.0.0.1:5092` 的演示进程；捕获后已逐图检查，未使用生产样数据、生产配置或
真实外网。移动浏览器 viewport 已显式设置并在页面内测得为 390×844；截图接口导出
的可见内容矩形为 375×811。测得 `document.scrollWidth=375`，未出现横向溢出，
筛选控件也未被底部 CTA 遮挡。

| 证据文件 | 验收场景 | 状态 |
| --- | --- | --- |
| `evidence/content-industry-desktop.png` | desktop 行业→场景→服务链路 | 已捕获并检查；1425×891；页面显示行业关联场景、适用部门和服务包 |
| `evidence/content-scenario-mobile.png` | 390×844 viewport 的场景筛选，无横向溢出或控件遮挡 | 已捕获并检查；截图内容矩形 375×811；制造业+生产+探索+50 的交集只显示“制造知识助手” |
| `evidence/content-keyboard.png` | 原生键盘筛选/详情焦点 | 已捕获并检查；462×1041；外部 Edge 原生 Tab/Enter 聚焦详情，蓝色 2.66667px 轮廓；SHA-256 `562EAD00B11DA7899D7F283506B01780E040AF92597111BEBADCA05C2361BA11` |
| `evidence/content-admin-publish.png` | 原生后台键盘发布/冲突恢复 | 已捕获并检查；1681×754；外部 Edge 原生键盘 stale-lock 冲突页；SHA-256 `C96B76687CB902FCC50AEA1D776D5AB5C513B97B284704AA20AEF1BDD491C911` |
| `evidence/content-case-resource.png` | 核验标签、来源、指标周期、附件且无联系方式 | 已捕获并检查；1440×900；资源页显示来源、审核时间、HTTPS 原文、版权说明和附件；同会话案例页核对了匿名标签与 30 天指标周期 |

五张文件的 SHA-256（按表中顺序）分别为
`26EA9F56021A7FCF1D051A34F9DEB7BBF4869FBA934540DC68B01774E7B443D6`、
`DF7D57F92F280EC1CE0AC8C7A75DBA9DA767474299AE01E0A351062CB8438D56`、
`562EAD00B11DA7899D7F283506B01780E040AF92597111BEBADCA05C2361BA11`、
`C96B76687CB902FCC50AEA1D776D5AB5C513B97B284704AA20AEF1BDD491C911`
和 `01B36BFC0FC55C3853D0772B8FC420C67AFCEEB45CA0CD72F3BAB55B26B4580D`。

**已被后续外部 Edge 原生键盘证据取代的历史限制：** 本轮内置浏览器能移动真实焦点并读取 `activeElement`/计算样式，但其可用输入后端
无法执行 Tab、Enter 或原生 select 键盘动作；三种受支持的 keypress 入口虽返回
成功，`activeElement` 仍停留在 `BODY`，未产生默认键盘行为。因此“可见焦点”有
截图和既有 Node 回归证据，完整管理员
状态流有真实 HTTP 证据，但**纯键盘筛选、详情导航和后台全流程为 NOT PROVEN**，
不能用鼠标点击结果替代。该限制必须交由独立审查判定，若属阻断项则在 Task 12
内补充具备原生键盘输入能力的本地验收，不得带着未知项进入 Task 13。该历史结论已由下节关闭；当前阻断仅为 200% zoom/reflow。

浏览器截图只能证明捕获时可见的页面状态；自动化测试继续负责权限、CSRF、事务、
幂等、过期边界、私有字段不公开和 no-delete 等不可由单张截图证明的约束。

## Controller Fix 2: external Edge native-keyboard evidence

控制器使用外部默认 Edge 的原生 CUA 键盘事件（不是 locator 点击或程序化 focus）在
一次性本地 fixture 上补足键盘矩阵：从 `/scenarios` 的 BODY 经 Tab 到所有筛选控件，
焦点为 `rgb(15, 111, 239) solid 2.66667px`；用 Enter 提交制造业、生产、探索和
20 条/页，结果仅为 `mfg_knowledge_assistant`，再用 Shift+Tab/Tab/Enter 访问详情。
原生键盘还完成管理员登录、scenario 11 的 Add block/Space 加标题/Shift+Tab×4+Space
排序、浏览器必填标题校验、保存、发布、修订、stale-lock 冲突恢复（保留提交值）和
归档后 404。

资源分页已用 `extend` 填充真实持久数据：第一页 20 张、从 BODY 经 31 次原生 Tab 到
页 2 链接再 Enter、第二页 5 张，两个页面 slug 集合互异。评估配置为 200/12 questions；
原生键盘完成全部 6 个可见向导步骤、预览、仅本地 dummy 身份/同意/提交，报告显示
`AI 转型评估报告`、67 分、`规模扩展`、六维度及已发布场景/服务推荐。没有外部传输。

替换截图：`content-admin-publish.png` 为 1681×754、66,598 bytes、SHA-256
`C96B76687CB902FCC50AEA1D776D5AB5C513B97B284704AA20AEF1BDD491C911`；
`content-keyboard.png` 为 462×1041、44,016 bytes、SHA-256
`562EAD00B11DA7899D7F283506B01780E040AF92597111BEBADCA05C2361BA11`。其余三张
哈希不变。因此纯键盘 P2 B 已 PROVEN/closed。

**200% 补证前的历史检查点：** 代表性本地 Edge 基线为 DPR 1.125、innerWidth 1698、
clientWidth/scrollWidth 1681；`edge://settings/appearance` 被策略阻断且禁止自动化绕过。
随后 200% 菜单截图和 live narrow metrics 已关闭该 finding，证据见下段。最终 task-level
re-review 和控制器 focused/static/full 均尚未运行，Task 13、最终 full 与部署继续冻结。
fixture 仅暂留 `127.0.0.1:5092` 等待控制器清理；已批准
`127.0.0.1:62767` preview 不受影响。

Scoped re-review 先确认两项可修复 finding 已 ADDRESSED：定时发布回显（RED `1 failed in 0.97s`、narrow GREEN `3 passed in 1.92s`）和主证据/哈希/开篇状态一致性；无新 Critical/Important。该检查点之后，200% zoom/reflow 也已由下述证据关闭。Task 12 仍待最终 task-level review、controller focused/static/final-full、commit 与 cleanup；Task 13 与部署继续冻结。

控制器随后以用户提供的 Edge 200% 菜单截图（`127.0.0.1:5092` 可见，SHA-256 `03D9B918ECBF76DABC2556DDEA236F8BE6DB7EFC42B997EBAE4F872088A59E75`）和全页截图（SHA-256 `129F8242F358C88987A0131BA46165E4E0FB336DE2A03640C2270815DF182791`）关闭该 finding。200% live metrics 为 DPR 2.5、innerWidth 764、clientWidth=scrollWidth=756；home、场景、评估和本地 admin login 均无横向溢出/越界控件。因此 200% zoom/reflow 为 PROVEN/CLOSED（非 DPR 比率推断）。Task 12 仍待最终独立复审、controller focused/static/final-full、commit 与 cleanup；Task 13/部署冻结。

当前 focused verification 将过时的组合标点断言改为 `[data-case-metric]` 内分别存在统计周期标签和值。该检查通过后暴露独立当前 RED：已发布资源附件下载返回 404；两文件精确集为 `1 failed, 26 passed in 18.96s`，未作产品修复或运行 full。

## Final controller closure

附件 404 的根因是公共资源详情使用 `CONTENT_NOW_PROVIDER`，而媒体端点仍直接读取
机器时钟，导致同一来源检查在页面与下载授权中产生不同的七天新鲜度判断。媒体
image/download 路由现显式传入统一内容时钟；继续运行旅程后发现行业、场景、服务、
案例八个目录路由也绕过了已有 `_content_now()`，现已全部统一。旧测试对内部
`shanghai_now` 的 monkeypatch 已迁移到公开的应用配置 seam，原有效期、未来发布、
共享引用和 fail-closed 断言均保留。

- 媒体窄测：`38 passed in 26.06s`；目录时钟路由：`9 passed in 6.16s`。
- 主控四文件集中回归：`352 passed in 206.06s (0:03:26)`。
- 最新冻结审查包：96,934 bytes，SHA-256
  `E2674578A44DE2FDEFEEB42A7011790015F36AB8AFD7CAB30558AF1A5C7F595C`；
  独立 scoped review 为 **Approved**，无 Critical/Important。唯一 Minor 是缺少
  provider 缺失时 fallback 的隔离诊断测试，不影响现有回退实现或发布安全结论。
- 唯一 final full：`1653 passed in 779.80s (0:12:59)`，exit 0。
- 一次性 5092 listener PID 12408 已精确停止；验证 `127.0.0.1:5092` TCP closed。
  已批准的 62767 listener PID 31692 保持运行，TCP open，未被触碰。

本轮未部署、未联网、未安装依赖、未读取或修改生产/真实数据库，也未更改
Nginx、systemd 或公网暴露。Task 13 必须作为后续独立任务开始，部署仍需满足
全局上线批准与阶段 7 门禁。
