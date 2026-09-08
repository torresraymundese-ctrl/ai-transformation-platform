# Windows CSS 换行兼容验收（2026-09-08）

## 原因与范围

本地基础分支 `codex/ai-platform-2.0` 从 `46d9dc3` 快进合并至 `1558244` 后，全量测试得到 **4 failed、2237 passed（1315.35s）**。四项均为 `tests/test_ui_foundations.py` 中的 CSS 多行文本断言，不是合并冲突。

`git ls-files --eol` 显示三个相关 CSS 文件在主目录为 `i/lf w/crlf`，功能工作区为 `i/lf w/lf`。两分支代码树相同。对照运行四项：主目录 4 failed（2.80s），功能工作区 4 passed（2.65s）。主目录静态响应保留了 CRLF，测试却要求 LF。

用户批准修复后，仅调整测试工具：

- 顶层与媒体查询内的规则解析在匹配前将 CRLF 转为 LF。
- 页脚断言仍查找同一组选择器并检查同一 `color` 值，不再依赖原始文本的精确换行。
- 新增 LF/CRLF 参数化对照，覆盖顶层规则、媒体查询规则及错误选择器被拒绝。

没有修改公开页面 CSS、报告/PDF、应用逻辑、Git 换行配置或生产数据。原工作区及未提交内容保留。

## 测试驱动记录

1. 顶层解析对照 RED：LF 通过，CRLF 失败（1 failed、1 passed）。
2. 首次修复后的 UI 文件：67 passed、1 failed；失败揭示同一用例后续媒体查询解析也要求 LF。
3. 扩展媒体查询对照 RED：LF 通过，CRLF 失败（1 failed、1 passed）。
4. 两条读取路径修复后的整个 UI 文件：**68 passed in 47.90s**。
5. 全部 8 个 Node 测试文件：**50 passed、0 failed、0 skipped，423.5744ms**。

独立只读复核无 Critical、Important 或 Minor 问题，确认没有放宽选择器或颜色回归检查。

## 整仓验证与临时空间

修复后的首轮整仓回归因 C 盘空间耗尽失败：**3 failed、1681 passed、559 errors，975.06s**。数据库报 `database or disk is full` / `disk I/O error`，随后命令工具也无法写启动日志；磁盘检查确认 C 盘可用空间为 0。该轮不能计为全量通过。

仅清理本任务刚生成的三处 `ai-final-*`、`ai-merged-*`、`ai-eol-final-*` 唯一临时目录（删除前核对绝对路径及目录类型），释放约 5.8 GB。它们是可重新生成的测试数据库和夹具，测试日志位于 D 盘并保留；没有清理其他 Temp 内容、用户数据、源码或预览数据库。

后续全量验证将 basetemp 放到工作区内的 D 盘 `.verification-tmp/css-eol-final-<唯一标识>`，并启用 `--maxfail=1`，以便遇到环境错误时及时停止。首次 D 盘启动因临时父目录不存在而以 1 个 setup error 停止；补建父目录后以全新子目录重新运行，没有为此修改应用或测试。

最终主目录整仓命令为 `python -m pytest -q --tb=short --maxfail=1 -p no:cacheprovider --basetemp=<D盘唯一临时目录>`，使用既有虚拟环境、`PYTHONHASHSEED=6` 和进程级 WeasyPrint DLL 路径，保持原 Windows 编码设置。

结果：**2,243 passed in 1265.66s（21:05），exit 0**，无失败、跳过或警告汇总。日志保留在功能工作区的 `.superpowers/sdd/2026-09-07-admin-experience-performance-closeout/merged-eol-fixed-drive-d-final-pytest.log`。该结果覆盖完整的修复后代码，而非将失败运行与定向重跑拼成一次通过。
