# Android 下拉选择、顶部栏与独立日刊 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. 本次按 dispatching-parallel-agents 分工，主代理整合接口并逐项验证。

**Goal:** 修复 APK 选择与顶部布局，接入手机独立新闻采集和真实 CST 自动更新。

**Architecture:** 正式 HTML/CSS/JS 继续由 WebView 复用，Android 单选使用可访问的锚定列表。Kotlin core 独立来源验证、日刊选择和 ArticleStore；Android 应用层负责安全网络、Keystore 翻译、Kuromoji、AlarmManager 与 WorkManager，任务不依赖 Activity 生命周期。

**Tech Stack:** Kotlin、Jsoup、OkHttp、Kuromoji IPADIC、AlarmManager、WorkManager、原生 JavaScript。

**Spec:** 用户 2026-10-01 的三项修复要求及“同时接入手机独立采集与定时更新”选择；根 AGENTS.md。

## Global Constraints

- 最低 Android 10，包名 `jp.fujimi.newsbunko.next`；不修改 `apk-original/`，不写活动文库测试。
- 单列方案 A、原控件 ID、API 字段和值类型保持；Web/PC 不启用 APK 下拉替代层。
- 新闻文件为事实来源，创建命名沿用 PC；临时事务位于 diagnostics，内容无哈希对象库。
- 六家来源各自验证公开正文、会员、分页、媒体；先验证候选，再选择，最后仅处理入选新文章。
- 成功保存才计配额；已有有效文章保留；不足 partial/failed，不显示 100%。
- CST 定时、手动同步、关机错过不补跑；显示真实精确权限与后台延迟能力。
- TLS、公开地址、重定向、超时、体积限制不关闭；密钥不记录日志。

## Task 1: APK 选择与顶部布局

Files: `static/index.html`, `static/main.js`, `static/static.css`, `tests/verify_android_frontend.cjs`。

- [x] 复现原生单选弹窗对应控件，比较原 APK 的 computed header 样式。
- [x] 增强真实 Android 的 select：同值与 change 事件保留，动态 options/disabled/value 同步；按字段宽度展开，键盘、外点、返回关闭。
- [x] 修复 header 的重叠空白，保留 OS 安全区和抽屉。
- [x] 在 375/390/812/1440px 检查选择持久化、关闭与布局。

## Task 2: 六家来源

Files: `android/core/src/{main,test}/kotlin/jp/fujimi/newsbunko/next/news/`。

接口：`NewsTransport.get(url): NewsPage`；`NewsProvider.collect(homepage, transport, checkpoint): List<String>`、`fetchArticle(url, transport, checkpoint): NewsArticle`。

- [x] 写付费、正文容器、推荐排除、Yahoo 分页归属的失败测试。
- [x] 按 PC 规则实现独立 provider；未知结构明确拒绝。
- [x] 候选验证不写文件、翻译或下载媒体，checkpoint 包围请求与处理。

## Task 3: 日刊与存储

Files: `android/core/src/{main,test}/kotlin/jp/fujimi/newsbunko/next/daily/`、`store/ArticleStore.kt`。

接口：`DailyCoordinator(dataRoot).run(DailyRequest, transport, postprocess, checkpoint, onProgress): JSONObject`；`PostprocessedArticle` 保存译文、假名、媒体及明确错误；`ArticleStore.create` 返回 `ArticleSnapshot`。

- [x] 用临时目录测试三阶段、配额、重试、取消、PC ArticleReader 可读和事务恢复。
- [x] 创建正文、译文、假名分文件及 PC schema manifest；数值 ID、标题目录不随正文变化。
- [x] 候选排除只入 candidate_stats；真正来源读取和后处理失败入 errors。

## Task 4: 手机运行与 CST 后台

Files: `android/app/src/main/java/.../daily/`, `bridge/MobileBridge.kt`, `settings/LocalSettingsApi.kt`, `MainActivity.kt`, `AndroidManifest.xml`。

- [x] pure core 测试固定 CST 下一个未来时刻、跳过错过日期和无效输入。
- [x] 接入安全公开 HTTPS 下载；凭据仅传 DeepSeek 固定 HTTPS endpoint；检查段落数和顺序，已有原文不丢失。
- [x] AlarmManager 触发独立 WorkManager 日刊任务；精确权限没有时使用时间窗口，真实披露；开机只重排未来，不补任务。
- [x] 任务保存在应用私有偏好，进程中断标为 interrupted；取消用独立任务代际，重试保留已存文章。
- [x] API 提供真实 generate、status、cancel、schedule、capability；浏览器轮询反映实际结果。

## Task 5: 验收与 1.0.3 安装包

- [x] 合并后运行 core、Android device tests、三个前端 syntax 与布局检查，所有测试使用临时文库或隔离模拟器。
- [x] 比较合成 PC/Android 文件格式；实际联网分别记录发现候选、公开正文与保存结果。
- [x] 打包原发布签名 APK，校验 manifest、签名、SHA-256 和正式资源逐字节一致；模拟器安装启动。
- [x] 记录尚未完成的真机、电源/网络限制与实站覆盖，不把接口成功等同功能完成。
