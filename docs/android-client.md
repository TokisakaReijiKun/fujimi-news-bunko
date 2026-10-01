# Android 客户端

Android 工程位于 `android/`，包名为 `jp.fujimi.newsbunko.next`，最低支持 Android 10。它使用 WebView 加载正式 `static/` 页面，并通过 `FujimiMobile` 原生桥接访问应用私有文库；原 APK 的包名和私有数据不会被覆盖。

## 构建与签名

先安装 Android SDK Platform 36、Build Tools 36.0.0 和 Gradle 9.6。SDK 可放在 `%LOCALAPPDATA%/Android/Sdk`、`C:\Android\Sdk`，也可通过 `ANDROID_HOME` 或 `ANDROID_SDK_ROOT` 指定。

```powershell
./build-android.ps1                 # debug 安装包
./build-android.ps1 -Release        # 本机发布签名配置
```

Debug APK 和 SHA-256 位于 `dist/FujimiShinbunBunkoAndroid/`。Release 构建使用 `%LOCALAPPDATA%/FujimiShinbunBunko/signing/` 下的本机密钥与 DPAPI 保护的凭据文件；密钥不在仓库内，也不会写入文库。正式分发前需把该密钥安全备份到发布密钥库。

当前 release APK（1.0.2）：`dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-1.0.2-release.apk`，SHA-256：`d6b8d859932ac7dc3f7be70a5e8e79d1d54ec6454905fdc4ca5cf4de4d560cf9`；APK Signature Scheme v2 验证通过。方案 A 设置页的本次验证记录见 [android-settings-a-acceptance.md](android-settings-a-acceptance.md)。

## 设置页与本机能力

1.0.2 采用方案 A：保持原有竖向页面和操作流程，使用浅绿底色、白色分组卡片、统一按钮及状态标签；应用信息与文库路径单独显示，来源配额和文库路径仍可展开。页面直接显示原生接口返回的真实状态，演示数据与 Demo 控件不进入 APK。

设置页现在保存并显示真实的本机状态：

- Android 不再枚举或自动选择系统 `ja` 声线。设置页固定提供 PC 客户端同源的 Edge 在线声线「圭太」（`ja-JP-KeitaNeural`）和「七海」（`ja-JP-NanamiNeural`），显示名称为「システム音声（圭太／七海）」。选择值按 Edge 声线 ID 保存，不会把中文系统声线当成日语声线。
- Android 即时朗读直接使用 Edge TTS WebSocket 服务获取真实 MP3，不依赖 PC 地址；请求音频只暂存在 `data/diagnostics/`，播放结束即删除。Edge TTS 不可用或网络失败时明确返回错误，不静默切换到 Android 系统声线。PC 地址只用于文库协同。
- DeepSeek 密钥使用 Android Keystore 的 AES-GCM 加密，密文只放在应用私有偏好中；清除操作会删除密文和初始化向量，密钥不会同步。
- 书架排序、新闻目标数、来源名称/HTTPS 网址/最低配额和手动日刊模式会经过字段校验后保存。Android 日刊采集、自动调度、PC Irodori 声线仍显示为未接入，按钮不会假装成功。
- PC 地址只接受 HTTPS 私网 IPv4，不接受公网、账号、查询参数或路径。检测有 8 秒网络超时和 20 秒界面超时；失败保留地址并显示原因。`立即同步` 在配对和双向合并未完成前保持禁用，不会偷偷传输文库。
- 返回键先关闭对话框、抽屉和词典详情，再返回 WebView；文件导入使用系统选择器。系统栏、刘海、键盘和横屏区域使用安全区内边距。

## 文库位置

APP 使用私有目录 `files/data/`，并沿用 PC 的 `articles/`、`bookmarks/`、`books/`、`voices/`、`backups/` 和 `diagnostics/` 结构。同步文件按源端相对路径写入，保留目录名、文件名和扩展名；SHA-256 仅用于校验。词典原库只读复制到应用私有 `dictionary/dictionary.sqlite3`，搜索投影位于 `data/dictionary-search.sqlite3`，不修改原库。

当前已接入本地文件格式读取、日刊文章查询、正式前端资源、Edge 在线即时朗读桥接、词典和路径保留的同步文件安装核心。PC 配对、双向同步、完整新闻采集、EPUB 导入和媒体后台播放仍需继续接入；未完成能力会返回明确错误，不显示假成功。

## 此前功能验证记录（非 1.0.2 本次回归）

- `android :core:test`：13 项通过（路径存储、文章读取、设置校验）。
- `android :app:assembleDebug :app:assembleDebugAndroidTest`：通过。
- Android 模拟器 Pixel 5 / API 35：3 项 `SettingsDeviceTest` 通过；包安装、Keystore 保存/清除、设置跨 Activity 重建和地址校验通过。
- WebView CDP 验证：词典 `159396` 词条、日语搜索、圭太／七海 Edge 声线目录、设置真实状态、网络不可用时的 TTS 错误反馈通过。
- Edge 无头布局：1440px、375px、390px 和横屏 812px 均无横向溢出；截图与 JSON 证据在 `build/qa/android-settings/`。
- Python Tokyo 全量回归：237 项通过；三个前端文件 `node --check` 和 `git diff --check` 通过。

模拟器未连接可用的 Edge TTS 网络，因此朗读运行结果为明确的 `error`；在实际设备上需允许网络访问 Edge TTS 服务。
