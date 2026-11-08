# 设置页方案 A：1.0.2 交付记录

日期：2026-10-01。

## 变化

- 将已选定的方案 A 接入正式 `static/index.html`、`static/static.css` 和 `static/main.js`。保留单列竖向排列、原有设置字段、接口和操作流程。
- 统一六组卡片的标题、编号、留白、状态与按钮；将应用信息和可展开的文库路径单独成组。Android 声线列表保持可见，来源配额仍按原流程展开。
- 修复 Android 的“选择声线”按钮被 PC Irodori 可用性检查误禁用的问题。保留目前实际提供的圭太／七海声线，不使用 Demo 中的模拟系统声线。
- 日刊生成、自动调度和同步仍按真实能力显示未接入状态；保留禁用和错误反馈。
- Android 版本改为 `1.0.2`，`versionCode=3`。设置页从安装包元数据读取版本号，避免再次显示旧版本。

## 安装包

| 项目 | 结果 |
| --- | --- |
| 文件 | `dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-1.0.2-release.apk` |
| 大小 | 69,802,307 字节 |
| 包名 | `jp.fujimi.newsbunko.next` |
| 最低 Android 版本 | Android 10，API 29 |
| target SDK | 35 |
| APK SHA-256 | `d6b8d859932ac7dc3f7be70a5e8e79d1d54ec6454905fdc4ca5cf4de4d560cf9` |
| 签名 | 沿用本机既有发布密钥，APK Signature Scheme v2 校验通过 |
| 证书 SHA-256 | `5fd16c5eeb88d2f10b31f07fd0bb6386cdc353cc1ff904c4d296a8ced492e16b` |

同目录提供 `.apk.sha256` 校验文件，通用 `FujimiShinbunBunkoAndroid-release.apk` 与上述版本化安装包内容相同。

## 本次验证

- `./build-android.ps1` 和 `./build-android.ps1 -Release` 构建成功；release 的 lint 检查通过。core 的 13 项测试结果为零失败、零错误，本次 Gradle 判定这些未修改的核心测试任务为 `UP-TO-DATE`。
- `SettingsDeviceTest` 在隔离的 Pixel 5 / Android 15 API 35 模拟器上通过 3 项测试：Keystore 密钥保存与清除、设置跨 Activity 重建持久化、PC 地址校验且不触发同步。仅使用模拟器测试数据。
- 实际 debug APK WebView 检查：375px 无横向溢出，六组卡片可见，显示版本 1.0.2；声线按钮可用，选择框实际包含圭太和七海；未接入的同步和日刊生成保持禁用。
- 正式前端页面的隔离接口样本检查通过 375px、390px、812px 横屏和 1440px 桌面四种布局。验证了声线选择、书架排序、新闻目标数、来源展开、网络开关和路径展开；无页面异常、横向溢出或不可达控件。这些样本检查不证明新闻采集、PC 同步或真实网络朗读能力。
- 三份正式 JavaScript 文件的 `node --check` 通过；`git diff --check` 通过。
- 对 release APK 解包核对：`index.html`、`static.css`、`main.js`、`book-reader.js` 和 `browser-speech.js` 与当前正式前端逐字节一致，未包含 Demo 页面。
- 最终签名 release APK 在同一隔离模拟器上安装成功，主 Activity 冷启动成功。

截图、布局结果、原生检查结果与资源校验记录位于 `build/qa/settings-a-release/`。检查脚本为 `tests/verify_settings_a_release.cjs` 和 `tests/verify_settings_a_webview.cjs`。

未完成真实手机安装、真实声线出声、锁屏和长时间使用验收。本次未运行 Python 全量回归：工作区原有 Python 测试文件已被删除，保持该既有状态；本次未修改 Python 后端。

## 数据与安装说明

本次不迁移或改名文库，不修改活动 `data/` 或 `apk-original/`，无用户数据备份产生。密钥继续保存在仓库外的 `%LOCALAPPDATA%/FujimiShinbunBunko/signing/`，未复制到文库或安装包。

使用 Android 安装器打开上述 APK。此前安装的是同包名、同发布签名版本时可直接更新；如果安装器报告签名不同，请先保全旧版本文库，避免直接卸载。

文库存放在应用私有 `files/data/`，卸载会删除。当前双向同步和应用内文库备份导出尚未接入，不能依靠“立即同步”保全文库。有数据的设备应优先覆盖更新；需要卸载时先使用设备允许的备份方式完整导出私有文库，并核验目录及文件可恢复，再卸载。
