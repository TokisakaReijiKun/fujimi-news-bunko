# Android 客户端

Android 工程位于 `android/`，包名为 `jp.fujimi.newsbunko.next`，最低支持 Android 10。它使用 WebView 加载正式 `static/` 页面，并通过 `FujimiMobile` 原生桥接访问手机公共文库；原 APK 的包名和私有数据不会被覆盖。

## 构建与签名

先安装 Android SDK Platform 36、Build Tools 36.0.0 和 Gradle 9.6。SDK 可放在 `%LOCALAPPDATA%/Android/Sdk`、`C:\Android\Sdk`，也可通过 `ANDROID_HOME` 或 `ANDROID_SDK_ROOT` 指定。

```powershell
./build-android.ps1                 # debug 安装包
./build-android.ps1 -Release        # 本机发布签名配置
```

Debug APK 和 SHA-256 位于 `dist/FujimiShinbunBunkoAndroid/`。Release 构建使用 `%LOCALAPPDATA%/FujimiShinbunBunko/signing/` 下的本机密钥与 DPAPI 保护的凭据文件；密钥不在仓库内，也不会写入文库。正式分发前需把该密钥安全备份到发布密钥库。

当前 release APK（1.0.7）：`dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-1.0.7-release.apk`；沿用原发布签名。文章完整音频继续按 PC `/edge-tts` 实现保存和复用；本版把 PC 的 NHK 海外匿名授权与短期 `hdnts` 播放令牌流程接入 APP，并允许 HLS 播放器加载授权后的 NHK 视频。1.0.6 的异步朗读播放修复、PC 任务条和底部错误 Toast继续保留。NHK HLS 在 Android 端按授权 URL 在线播放，不能宣称已转换为 PC 的本地 MP4；授权失败时仍显示明确提示。本次未在 vivo X200s 真机安装验证。详情见 [android-1.0.7-nhk-video.md](android-1.0.7-nhk-video.md)；此前音频记录见 [android-1.0.6-audio-fix.md](android-1.0.6-audio-fix.md)。

## 设置页与本机能力

1.0.3 保留方案 A 的竖向页面、浅绿底色和六组卡片。APK 单选字段改为贴近字段展开的下拉列表，包括排序、浏览器声线和来源朗读模式；顶部恢复原页面标题栏结构，不新增蓝色应用身份栏。按原版 APK 对照，Android WebView 使用 edge-to-edge，抽屉覆盖系统状态栏和底部手势区，避免上下白栏。Web/PC 继续使用原控件与布局，演示数据与 Demo 控件不进入 APK。

设置页现在保存并显示真实的本机状态：

- Android 不再枚举或自动选择系统 `ja` 声线。设置页固定提供 PC 客户端同源的 Edge 在线声线「圭太」（`ja-JP-KeitaNeural`）和「七海」（`ja-JP-NanamiNeural`），显示名称为「システム音声（圭太／七海）」。选择值按 Edge 声线 ID 保存，不会把中文系统声线当成日语声线。
- Android 直接使用与 PC edge-tts 相同的 Edge TTS 服务获取真实 MP3，不依赖 PC 地址。文章首次点击朗读或“読み返し”时生成整篇音频，校验后通过 ArticleStore 保存到该文章的 `audio/圭太_标题.mp3` 或 `audio/七海_标题.mp3`，命名和逐句时间映射沿用 PC `/edge-tts` 规则。之后直接播放保存的文件，支持离线播放与段落跳转。失败保留已有音频；正文版本改变时拒绝提交旧音频。词典及未入库文本的即时朗读仍仅暂存在 `data/diagnostics/`，播放结束删除。Edge TTS 不可用时明确报错，不静默替换声线；首次合成需要联网，PC 地址只用于文库协同。
- 1.0.8 接入原 APK 既有的 Media3 播放桥接，直接定位本地文章音频；Edge 逐句起点保持原始时间，跨请求使用 PC edge-tts 的累计 MP3 字节时钟。[段落定位验证记录](android-1.0.8-paragraph-seek.md) 包含实际解码 PCM、正式页面触摸、签名和真机限制。
- DeepSeek 密钥使用 Android Keystore 的 AES-GCM 加密，密文只放在应用私有偏好中；清除操作会删除密文和初始化向量，密钥不会同步。
- 书架排序、新闻目标数、来源名称/HTTPS 网址/最低配额和日刊模式经过校验后保存。六家新闻来源分别验证公开正文、付费门槛和分页；三阶段日刊先验证候选，再按配额选择，仅后处理入选新文章。离线假名使用 Kuromoji IPADIC，已存在 ruby 保留；配置密钥后使用 DeepSeek 翻译，严格检查段落数量和顺序。网络、媒体或翻译失败如实显示，不保存伪造结果。
- 自动更新使用 CST 一次性 AlarmManager 闹钟触发 WorkManager 任务，不依赖设置页存活；无精确权限时使用系统时间窗口并显示可能延迟。开机只安排未来更新，不补跑关机期间任务；跨日或延后超过两小时的任务跳过。进程中断保留已保存文章，显示中断状态，需手动重试。
- PC 地址只接受 HTTPS 私网 IPv4，不接受公网、账号、查询参数或路径。检测有 8 秒网络超时和 20 秒界面超时；失败保留地址并显示原因。`立即同步` 在配对和双向合并未完成前保持禁用，不会偷偷传输文库。
- 返回键先关闭对话框、抽屉和词典详情，再返回 WebView；文件导入使用系统选择器。系统栏、刘海、键盘和横屏区域使用安全区内边距。

## 文库位置

1.0.4 起，APP 文库位于 `/storage/emulated/0/富士見新聞文庫/data/`，可通过手机文件管理器或电脑连接后的“内部存储设备/富士見新聞文庫/data”查看。目录内沿用 PC 的 `articles/`、`bookmarks/`、`books/`、`voices/`、`backups/` 和 `diagnostics/` 结构，保留目录名、文件名和扩展名。首次打开通过系统页面授予存储权限后再初始化文库，不迁移旧私有文库，也不回退到私有路径。词典原库仍只读保存到私有 `dictionary/dictionary.sqlite3`，搜索投影在公共 `data/dictionary-search.sqlite3`；密钥与设置保持私有。卸载不删除公共文库，备份时复制整个 `富士見新聞文庫/data/`。

当前已接入本地文件格式读写、独立日刊采集及 CST 调度、日刊文章查询、正式前端资源、Edge 在线朗读及文章完整音频保存、词典和路径保留的同步文件安装核心。文章原文、译文、假名分别存为 PC 格式文件，附件使用原站文件名；`data/fujimi.sqlite3` 只保存可重建索引，不缓存正文。PC 配对、双向同步、PC Irodori 声线、EPUB 导入和媒体后台播放仍需继续接入；未完成能力会返回明确错误。

实际安装时选择“自动更新”，设置 CST 时间，并检查“网络与定时”中的权限和下一次安排。使用计费网络需主动开启“允许蜂窝网络”。首次使用可点击“今すぐ生成”查看真实任务进度。Android 强制停止、厂商省电限制和网络不可达会影响后台执行；重新打开后仅安排未来闹钟。

## 此前功能验证记录（非 1.0.2 本次回归）

- `android :core:test`：13 项通过（路径存储、文章读取、设置校验）。
- `android :app:assembleDebug :app:assembleDebugAndroidTest`：通过。
- Android 模拟器 Pixel 5 / API 35：3 项 `SettingsDeviceTest` 通过；包安装、Keystore 保存/清除、设置跨 Activity 重建和地址校验通过。
- WebView CDP 验证：词典 `159396` 词条、日语搜索、圭太／七海 Edge 声线目录、设置真实状态、网络不可用时的 TTS 错误反馈通过。
- Edge 无头布局：1440px、375px、390px 和横屏 812px 均无横向溢出；截图与 JSON 证据在 `build/qa/android-settings/`。
- Python Tokyo 全量回归：237 项通过；三个前端文件 `node --check` 和 `git diff --check` 通过。

上述为旧版本记录。1.0.6 已在模拟器实际访问 Edge TTS 并生成有效 MP3；本次证据以 1.0.6 验收记录为准。
