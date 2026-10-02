# Android 1.0.3 验收记录

日期：2026-10-01。范围：APK 下拉选择、顶部留白、手机独立新闻采集和 CST 自动更新。

## 交付安装包

| 项目 | 结果 |
| --- | --- |
| 文件 | `dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-1.0.3-release.apk` |
| 大小 | 69,975,811 字节 |
| 包名／版本 | `jp.fujimi.newsbunko.next`，1.0.3，versionCode 4 |
| 最低／目标版本 | Android 10 API 29／API 35 |
| SHA-256 | `f634c624fbd5af1dc6cab983e1feac29f8e5220248397f36dbe7974acc3908eb` |
| 签名 | 沿用 1.0.2 的发布密钥，APK Signature Scheme v2 校验通过 |
| 证书 SHA-256 | `5fd16c5eeb88d2f10b31f07fd0bb6386cdc353cc1ff904c4d296a8ced492e16b` |

通用 release APK 与版本化 APK 字节一致；同目录附有 SHA-256 文件。发布密钥及保护凭据继续存放在仓库外 `%LOCALAPPDATA%/FujimiShinbunBunko/signing/`，未进入文库或 APK。

## 实际变化

- APK 的单选字段使用锚定下拉，保留原值、事件和设置接口；支持键盘、禁用选项、动态选项、外点关闭及 Android 返回键。声线仍是当前实际提供的 Edge 圭太／七海。
- 保留方案 A 单列卡片和原有页面标题／菜单结构。撤回此前新增的蓝色应用身份栏；Android 恢复原页面标题栏与原生状态栏处理，Web、PC 和手机浏览器布局不启用 APK 替代层。
- Kotlin 独立实现六家来源及三阶段日刊；会员、分页归属和正文校验发生在增强与写入之前。候选排除计入 candidate_stats；有效保存才计配额；已存在文章保留；不足显示 partial/failed，不能显示 100%。
- Android 使用受限公开 HTTPS 下载、离线 IPADIC 假名，以及配置密钥后的 DeepSeek 逐段翻译。媒体按原名保存并登记，未下载视频如实标为预览；失败不冒充成功。
- 自动更新使用 AlarmManager 触发 WorkManager；CST 下一次安排、精确权限或时间窗口可见。设置页关闭不取消任务。开机不补跑旧日刊，迟到超过两小时或跨日跳过；取消和重试各自使用独立任务身份。
- ArticleStore 写 PC schema 1 的正文／译文／假名文件和登记媒体，事务使用 diagnostics，SQLite 索引仅存元数据。索引失败显示告警和部分完成，已提交文件保留。数据库与文件序号共同保留取消／删除留下的历史 ID；收藏副本的数字 ID 也保留。

## 验证证据

- `./build-android.ps1`：debug 与设备测试 APK 构建成功。最终 core 63 项测试，零失败、零错误；后续仅 App／CSS 修正，release 构建该任务显示 UP-TO-DATE。
- `./build-android.ps1 -Release`：构建成功，release lintVital 通过。
- 隔离 Pixel 5 模拟器 `emulator-5554`（AVD `fujimi-settings-api35`），Android 15 API 35：最终 11 项设备测试全部通过。覆盖 Keystore、设置重建、实际闹钟设置／取消、安全 URL 和地址、媒体错误页拒绝、SQLite 与文件双向历史序号、仅收藏副本 ID、索引失败保留文件，以及实际 IPADIC 注音和已有 ruby 保留。
- 真实 debug APK WebView：375px、无横向溢出，88px 原页面标题栏、98px 首卡；CSS safe-area 为 0，原生系统栏只避让一次。真实触摸选择排序与七海声线，刷新后值保持；实际 Android 返回键先关闭下拉再关闭对话框。自动更新和立即生成可用，未接入同步继续禁用。
- 隔离前端 5＋4 场景全部通过，覆盖 APK 375/390/812px、手机浏览器 390px 和 PC 1440px。三个正式 JavaScript 语法检查通过，`git diff --check` 通过。
- 六家官网近期样本逐段对照 PC 解析结果；付费、推荐排除、Yahoo 分页和 NHK 异常正文拒绝均有回归。采样经开发机 HTTPS 代理，仅验证公开正文，不调用付费翻译或写用户文库。
- 合成临时文库 Android→Tokyo PC→Android 往返，19 个字段一致：稳定 ID、目录、修订、emoji、扩展汉字、换行、ruby、字符区间和媒体校验值保持。未使用活动 `data/`。
- 实际后台运行：在隔离模拟器设置未来 CST 精确闹钟，按 Home 离开应用，系统真实触发任务；计费网络未获许可时返回明确失败且进度为 0%。开启许可后的独立采集进入読売列表请求，但该模拟器网络发生 IOException，最终 0/1 failed，未产生虚假文章。没有把“任务已排队”作为采集成功。
- 发布 APK 中六份正式前端资源与源码逐字节一致，未含 Demo、官网测试 fixture 或历史预览页面。
- 在同一隔离模拟器先安装签名 1.0.2，再以 `install -r` 更新至最终签名 1.0.3，均成功；主 Activity 冷启动 Status ok，2343ms。真实用户设备未执行卸载或更新。

截图和 JSON 证据：`build/qa/android-frontend/`、`build/qa/settings-a-release/`、`build/qa/android-daily-runtime/`、`build/qa/android-storage-roundtrip/`、`build/qa/android-1.0.3/drawer-rollback.png`。核心 XML 位于 `%USERPROFILE%/.gradle/fujimi-android-build/core/test-results/test/`。

## 未完成的现场验证与限制

未完成真实手机安装、六家网站在手机网络上的全文采集／媒体下载、真实 DeepSeek 翻译、真实朗读出声、关机／厂商省电下的长期运行、Android 10 设备验证。模拟器已验证独立注音、存储、定时触发和真实错误反馈；它当前无法连通新闻站点，因此不能宣称本次模拟器已经生成完整真实日刊。

PC 配对与双向同步、PC 模型声线、EPUB 导入和完整媒体后台播放仍未接入；本次不把它们标记完成。本次未修改 Python 后端；工作区 Python 测试文件既有删除状态保持，未运行 Python 全量回归，也未把空测试集作为通过。

## 数据与安装恢复

文库沿用应用私有 `files/data/` 的 PC 目录及文件格式，没有迁移活动文库、重命名既有内容或修改 `apk-original/`。所有测试数据仅在临时目录、模拟器缓存或隔离模拟器文库；无真实用户数据备份产生。

同包名、同发布签名可覆盖更新。安装器提示签名不同时，先保全文库，不直接卸载。卸载会删除应用私有文库；当前双向同步与应用内备份导出未接入，不能依靠“立即同步”保全数据。需卸载时使用设备允许的方式完整导出私有 `files/data/` 并校验可恢复，再卸载。重试生成保留已保存文章，不会为满足配额删除现有文章。
