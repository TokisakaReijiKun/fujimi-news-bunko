# Android 1.0.5 验收记录

日期：2026-10-02。范围：按 PC 客户端保存文章的圭太／七海完整音频。

## 安装包

| 项目 | 结果 |
| --- | --- |
| 文件 | `dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-1.0.5-release.apk` |
| 大小 | 70,008,159 字节 |
| 包名／版本 | `jp.fujimi.newsbunko.next`，1.0.5，versionCode 6 |
| 最低／目标版本 | Android 10 API 29／API 35 |
| SHA-256 | `a28bf186b93df3ee3c1257683042c6c51fd6a1d77cd80f9cccc798109dedf31f` |
| 签名 | 沿用既有发布密钥，APK Signature Scheme v2 校验通过 |
| 证书 SHA-256 | `5fd16c5eeb88d2f10b31f07fd0bb6386cdc353cc1ff904c4d296a8ced492e16b` |

## 行为

- 本次按用户提供的原版 APK 做窗口对照：正常页面保留原版 112px 页面标题栏；WebView 采用原版的 edge-to-edge 窗口，抽屉背景覆盖状态栏和底部手势区，去除上下白色留白。证据见 `build/qa/android-1.0.5/fixed-normal.png`、`fixed-drawer.png` 与 `original-apk-drawer.png`。

- 文章首次点击朗读或“読み返し”，使用当前实际选择的圭太或七海合成完整 MP3，取得真实 SentenceBoundary 时间；整篇校验完成后保存并播放。长文合成按 UTF-8 长度分请求，输出完整 MP3，逐段时间使用实际音频偏移。
- 保存位置为 `/storage/emulated/0/富士見新聞文庫/data/articles/YYYY-MM-DD/创建时标题/audio/`。新文件使用 PC `/api/articles/<id>/edge-tts` 的 `圭太_标题.mp3`／`七海_标题.mp3` 规则，包含非法字符替换、Unicode 空白处理和 92 字符文件主名限制；原 PC 音频名及扩展名保持原样。重名处理沿用该 PC 接口的摘要与数字后缀，不建立哈希对象库。
- 相同正文、相同当前声线且完整文件有效时复用。页面再次打开播放现存文件，不请求 Edge 服务；可离线播放、拖动进度和点击段落跳转。更换声线生成对应音频，保留此前声线文件；只有当前元数据登记的声线可直接复用，切回旧声线仍遵循现有 PC 接口的生成规则。
- ArticleStore 执行可恢复的目录事务，正文版本在提交前再核对；原文、译文、假名、媒体及既有音频完整保留。新闻音频不加入媒体附件登记。网络、音频校验、段落匹配或保存失败如实报错，旧音频保留。
- WebView 从对应文章目录流式读取 WAV／MP3，支持 Range 请求；非法路径和未完成文件不可读取。未入库文本、词典仍使用即时朗读，临时文件位于 diagnostics 并在完成后清理。

## 验证

- `./build-android.ps1` 和 `./build-android.ps1 -Release` 成功，release lintVital 通过。核心全套 70 项测试，零失败，包含新增 7 项音频保存、复用、源版本核对、PC 命名、原名访问和段落时间测试。
- Android 15 API 35 模拟器 `emulator-5554`，AVD `fujimi-settings-api35`，设备型号 `sdk_gphone64_x86_64`：14 项设备测试通过。实际请求圭太、七海并保存有效 MP3，离线复用不调用合成，MediaPlayer 实际播放到完成，Range 返回精确字节；超过单次请求长度的长段落及包含 `A&B` 的正文合成通过。其余 12 项覆盖原设置、Keystore、公共目录、SQLite、来源网络规则和日刊能力。
- `tests/verify_android_saved_audio.cjs` 在正式 debug APK WebView 执行：点击原有朗读按钮只发送一次完整音频 POST，保存成功后播放；再次打开阻断合成请求仍能播放，第二段跳转成功，音频 SHA-256 不变，原文 SHA-256 不变。临时示例文章随后删除。证据：`build/qa/android-saved-audio/results.json`。
- `tests/verify_android_frontend.cjs` 的 5 个页面场景通过：APK 375/390/812px、手机浏览器 390px、PC 1440px；无横向溢出，设置下拉及原控件保持可用。三个正式 JavaScript 文件的 `node --check` 与 `git diff --check` 通过。
- 真实 debug WebView 指标：375 CSS px 下标题栏 112px、设置首卡 130px、safe-area 0；原版 APK 抽屉截图对照确认状态栏与底部手势区均无白栏。正式 Playwright 场景依赖当前工作区未安装 `playwright` 时未重复运行，设备 WebView 触摸与指标检查已执行。
- `tests/verify_settings_a_webview.cjs` 在 `emulator-5554` 完整通过：库排序和浏览器声线均使用页面下拉列表，Android 返回键先关闭列表／弹窗，选择值在刷新后保持，自动更新选项可用，日刊调度能力返回可用；WebView 首卡与原版标题栏指标保持一致。
- 签名 release APK 中 `index.html`、`main.js`、`static.css`、`book-reader.js`、`book-reader.css`、`browser-speech.js` 与正式源码逐字节一致，没有测试页面、Demo 或历史预览页。
- 当前 `tests/` 没有 Python `test_*.py` 文件，未把旧版本的 Python 237 项记录视为本次回归。所有 Python 检查使用 conda Tokyo。PC 后端本次未改动。

本次没有访问或迁移 PC 活动文库；测试使用临时目录与模拟器临时合成文章。未在 vivo X200s 真机安装验收，也未验证锁屏后台播放。首次合成依赖 Edge 服务联网可用，已保存音频可离线播放。

## 安装及备份

把签名 APK 复制到手机可见的下载文件夹后打开安装。APK 使用既有发布签名，可覆盖升级既有正式包。文库仍位于 `/storage/emulated/0/富士見新聞文庫/data/`；首次使用需授予存储访问权限。未迁移旧私有目录数据。备份时复制整个公共 `data/`，卸载应用不删除公共文库；密钥和本机设置仍由 Android 私有存储管理。
