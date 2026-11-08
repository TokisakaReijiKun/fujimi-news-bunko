# Android 客户端

Android 工程位于 `android/`，包名为 `jp.fujimi.newsbunko.next`，最低支持 Android 10。它使用 WebView 加载正式 `static/` 页面，并通过 `FujimiMobile` 原生桥接访问手机公共文库；原 APK 的包名和私有数据不会被覆盖。

## 构建与签名

先安装 Android SDK Platform 36、Build Tools 36.0.0 和 Gradle 9.6。SDK 可放在 `%LOCALAPPDATA%/Android/Sdk`、`C:\Android\Sdk`，也可通过 `ANDROID_HOME` 或 `ANDROID_SDK_ROOT` 指定。

```powershell
./build-android.ps1                 # debug 安装包
./build-android.ps1 -Release        # 本机发布签名配置
```

APK 位于 `dist/FujimiShinbunBunkoAndroid/`，统一命名为 `FujimiShinbunBunkoAndroid-<versionName>-<release|debug>.apk`；版本号读取本次 Gradle 构建产物的 `output-metadata.json`，不生成无版本号的通用文件名，也不再生成独立的 `.sha256` 校验文件。Release 构建使用 `%LOCALAPPDATA%/FujimiShinbunBunko/signing/` 下的本机密钥与 DPAPI 保护的凭据文件；密钥不在仓库内，也不会写入文库。正式分发前需把该密钥安全备份到发布密钥库。

当前 release APK（1.0.16）：`dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-1.0.16-release.apk`；沿用原发布签名。本版撤回播放器以外的整套移动端美化，恢复原有顶栏、抽屉、卡片、导入区、词典和设置页；保留 MOJi 播放控制和明确要求的新闻/书籍字号统一。系统底部避让与字体缩放信息只供播放器使用，不再改变其他页面布局。

已有扫码 Activity 覆盖 ZXing 默认的 `sensorLandscape`，固定为竖屏；继续复用现有相机预览、二维码识别和配对流程。

2026-10-24 扫码方向验证：API 35 模拟器中，新增设备测试先复现旧实现为横屏，再验证修复后为竖屏；从正式设置页触摸“扫码连接”打开 1080×2340 的竖屏界面，返回键取消后回到设置页、提示取消并恢复按钮。签名 release 构建通过，最终 APK 中扫码 Activity 的方向值为 `portrait`，签名与旧版一致。截图在 `build/qa/scanner-portrait/scanner.png`，结果在 `logs/scanner-portrait-device-green.log` 与 `logs/scanner-portrait-live.log`。实体手机相机画面尚未复验；本次未迁移文库数据或创建备份。

此前 1.0.11 修复同步媒体进入系统相册，以及已有录音被全局声线设置隐藏的问题；新闻和书籍统一使用原生播放器，旧录音按稳定声线 ID 兼容，书籍音频路径正确编码特殊字符。范围见 [设备同步](device-sync.md)。

此前 1.0.7 接入 PC 的 NHK 海外匿名授权与短期 `hdnts` 播放令牌流程，允许 HLS 播放器加载授权后的 NHK 视频。NHK HLS 在 Android 端按授权 URL 在线播放，未转换为 PC 的本地 MP4；授权失败时显示明确提示。详情见 [android-1.0.7-nhk-video.md](android-1.0.7-nhk-video.md)；此前音频记录见 [android-1.0.6-audio-fix.md](android-1.0.6-audio-fix.md)。

## 设置页与本机能力

1.0.3 保留方案 A 的竖向页面、浅绿底色和六组卡片。APK 单选字段改为贴近字段展开的下拉列表，包括排序、浏览器声线和来源朗读模式；顶部恢复原页面标题栏结构，不新增蓝色应用身份栏。按原版 APK 对照，Android WebView 使用 edge-to-edge，抽屉覆盖系统状态栏和底部手势区，避免上下白栏。Web/PC 继续使用原控件与布局，演示数据与 Demo 控件不进入 APK。

设置页现在保存并显示真实的本机状态：

- Android 不枚举或自动选择设备的 `ja` 声线。设置页提供 PC 客户端同源的 Edge 在线声线「圭太」（`ja-JP-KeitaNeural`）和「七海」（`ja-JP-NanamiNeural`）；同步后也提供 PC 的 Kokoro／VOICEVOX 目录及自定义参考声线。选择值保留稳定 ID，不会把自定义或 PC 系统声线自动改回 Edge。同步声线只使用已同步完整音频，模型合成仍在 PC 完成。
- Android 直接使用与 PC edge-tts 相同的 Edge TTS 服务获取真实 MP3，不依赖 PC 地址。文章首次点击朗读或“読み返し”时生成整篇音频，校验后通过 ArticleStore 保存到该文章的 `audio/圭太_标题.mp3` 或 `audio/七海_标题.mp3`，命名和逐句时间映射沿用 PC `/edge-tts` 规则。之后直接播放保存的文件，支持离线播放与段落跳转。失败保留已有音频；正文版本改变时拒绝提交旧音频。词典及未入库文本的即时朗读仍仅暂存在 `data/diagnostics/`，播放结束删除。Edge TTS 不可用时明确报错，不静默替换声线；首次合成需要联网，PC 地址只用于文库协同。
- 1.0.8 接入原 APK 既有的 Media3 播放桥接，直接定位本地文章音频；Edge 逐句起点保持原始时间，跨请求使用 PC edge-tts 的累计 MP3 字节时钟。[段落定位验证记录](android-1.0.8-paragraph-seek.md) 包含实际解码 PCM、正式页面触摸、签名和真机限制。
- DeepSeek 密钥使用 Android Keystore 的 AES-GCM 加密，密文只放在应用私有偏好中；清除操作会删除密文和初始化向量，密钥不会同步。
- 书架排序、新闻目标数、来源名称/HTTPS 网址/最低配额和日刊模式经过校验后保存。六家新闻来源分别验证公开正文、付费门槛和分页；三阶段日刊先验证候选，再按配额选择，仅后处理入选新文章。离线假名使用 Kuromoji IPADIC，已存在 ruby 保留；配置密钥后使用 DeepSeek 翻译，严格检查段落数量和顺序。网络、媒体或翻译失败如实显示，不保存伪造结果。
- 自动更新使用 CST 一次性 AlarmManager 闹钟触发 WorkManager 任务，不依赖设置页存活；无精确权限时使用系统时间窗口并显示可能延迟。开机只安排未来更新，不补跑关机期间任务；跨日或延后超过两小时的任务跳过。进程中断保留已保存文章，显示中断状态，需手动重试。
- PC 设置中的“文庫互联”可开启独立的局域网入口，显示推荐地址、二维码和 6 位配对码。Android 可扫码，也可输入地址与配对码；配对成功后点击“立即同步”才会双向补齐文库。地址只接受 HTTP/HTTPS 私网 IPv4，不接受公网、账号、查询参数或路径；当前 PC 默认提供 HTTP，只在同一可信私网使用。连接、配对和内容传输分别显示真实状态；失败保留已有内容并显示原因。用法和合并范围见 [设备同步](device-sync.md)。
- 返回键先关闭对话框、抽屉和词典详情，再返回 WebView；文件导入使用系统选择器。系统栏、刘海、键盘和横屏区域使用安全区内边距。

## 文库位置

1.0.4 起，APP 文库位于 `/storage/emulated/0/富士見新聞文庫/data/`，可通过手机文件管理器或电脑连接后的“内部存储设备/富士見新聞文庫/data”查看。目录内沿用 PC 的 `articles/`、`bookmarks/`、`books/`、`voices/`、`backups/` 和 `diagnostics/` 结构，保留目录名、文件名和扩展名。首次打开通过系统页面授予存储权限后再初始化文库，不迁移旧私有文库，也不回退到私有路径。词典原库仍只读保存到私有 `dictionary/dictionary.sqlite3`，搜索投影在公共 `data/dictionary-search.sqlite3`；密钥与设置保持私有。卸载不删除公共文库，备份时复制整个 `富士見新聞文庫/data/`。

当前已接入本地文件格式读写、独立日刊采集及 CST 调度、日刊文章查询、正式前端资源、Edge 在线朗读及文章完整音频保存、词典，以及 PC 配对和手动双向文库补齐。同步范围包括日刊文章、收藏状态、已导入书籍、阅读室示例和随内容保存的完整媒体/音频；同步后的书籍和示例可在正式页面读取。文章原文、译文、假名分别存为 PC 格式文件，附件使用原站文件名；`data/fujimi.sqlite3` 只保存可重建索引，不缓存正文。Android 的 PC Irodori 模型声线、本机 EPUB 导入和其他未接入的书籍编辑操作仍返回明确错误。同步不代表这些能力已经实现。

实际安装时选择“自动更新”，设置 CST 时间，并检查“网络与定时”中的权限和下一次安排。使用计费网络需主动开启“允许蜂窝网络”。首次使用可点击“今すぐ生成”查看真实任务进度。Android 强制停止、厂商省电限制和网络不可达会影响后台执行；重新打开后仅安排未来闹钟。

## 此前功能验证记录（非 1.0.2 本次回归）

- `android :core:test`：13 项通过（路径存储、文章读取、设置校验）。
- `android :app:assembleDebug :app:assembleDebugAndroidTest`：通过。
- Android 模拟器 Pixel 5 / API 35：3 项 `SettingsDeviceTest` 通过；包安装、Keystore 保存/清除、设置跨 Activity 重建和地址校验通过。
- WebView CDP 验证：词典 `159396` 词条、日语搜索、圭太／七海 Edge 声线目录、设置真实状态、网络不可用时的 TTS 错误反馈通过。
- Edge 无头布局：1440px、375px、390px 和横屏 812px 均无横向溢出；截图与 JSON 证据在 `build/qa/android-settings/`。
- Python Tokyo 全量回归：237 项通过；三个前端文件 `node --check` 和 `git diff --check` 通过。

上述为旧版本记录。1.0.6 已在模拟器实际访问 Edge TTS 并生成有效 MP3；当前 1.0.11 的文库及声线同步验收见 [设备同步](device-sync.md)。
