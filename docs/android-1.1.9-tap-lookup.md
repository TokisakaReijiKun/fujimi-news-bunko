# 1.1.9：文章点词直接查词

用户选择仅移植 Moji 阅读的“点词直接查词”。依据提供的 `data/Moji阅读.apk.1` 中 `MOJiArticleDetail-121467f1.js` 的 `clickContentResponse` / `ne` 分支、`.on-click-word` 样式，以及 `layout_reader_word_dialog`、`reader_word_expand_dialog_layout` 迁移交互。

点击手机文章原文词语后，短暂高亮 500ms，并在底部打开释义。点 ruby 假名仍查询对应正文，普通正文使用 WebView 的日语词边界分段。面板采用原版粉色高亮、顶部 16px 圆角和约 180px 紧凑高度，长词条可在面板内滚动，最高 380px。复用既有词典 API、完整词条和发音按钮；点词不会同时触发段落播放，支持键盘及 Android 返回关闭。

精确匹配的词条直接显示释义；只有前缀候选时保留候选列表，不把不同复合词冒充当前词语。未收录词显示查询结果为空。没有增加长按菜单、替换词库、修改 PC 客户端或文库数据，也没有数据迁移或手工备份。

改动由 `data-redesign-app` 标记隔离。手机构建以已发布 1.1.8 的资源为基线，仅更新 `main.js`、`mobile-reader.css`、`index.html` 中本次必要内容，保留工作区此前已有的 PC 设置文案修改，不将其顺带带入手机包。

验证使用实际待打包资源和临时 API 样本：375/390px 触摸点击原文／假名、快速换词、前缀候选、空结果、返回及键盘操作，另检查桌面原有划词查询。证据为 `build/qa/mobile-word-lookup/results.json` 和对应截图；同目录 `staged-assets.json` 记录资源范围。未做手机实机安装验证。静态 APK 分析记录在 `build/research/moji-lookup/`；使用 APK 脚本、aapt2 和 apkanalyzer，未运行 Moji APK 或接入其服务。

review-agent 对本次增量进行了只读检查：No findings.

安装包为 `dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-1.1.9-release.apk`，versionCode 32，沿用原包名和签名，可覆盖安装保留文库。

交付核对：Release 构建成功，118 项 core 测试无失败；签名与旧版一致，26 个界面／词典资源核对完毕，仅上述 3 个资源变化。待打包资源的六个主视图、两种阅读器、375/390/1100px 应用检查及阅读字号／桌面隔离检查通过。发布核对记录为 `build/qa/mobile-word-lookup/release-check.json`。
