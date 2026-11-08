# 1.1.13：恢复 Moji 原版文章查词卡片

根据用户提供的 Moji 截图和 APK 的 `word_expand_dialog_layout` 修正上一版选错的阅读器底部面板。使用 APK 中 `bg_word_expand` 的 #1c1c1e 背景、#3b3b3b 边框和四角 16px 圆角；左右留 16px，底部留边并计入安全区。卡片高度 246px，保留关闭、同排词头／读音／音调、词性、收藏、发音，以及底部各半的“详情”和“MOJi辞書”入口。

六张图标直接从用户 APK 提取到 `static/lookup_assets/`，打包时逐字节核对原件。简卡参照原生 WordExpandView 拼接中日释义，只在释义区域滚动；例句、语源等完整内容放在详情，返回后恢复简卡并保留文章位置。读音优先使用词库，缺少时使用该正文词的 ruby；没有登记的词性／声调不伪造。

收藏通过原词条 ID 保存在当前端的浏览器存储中，未接 Moji 账号同步。“MOJi辞書”使用 APK 中的 `mojisho://mojidict.com?search=` 协议，原生桥只允许交给 `com.mojitec.mojidict`；未安装时明确提示。发音沿用已选声线。

375/390px 待打包资源检查通过：卡片尺寸和配色、假名点词、释义独立滚动、收藏重开保留、详情／返回、快速切词、候选和空结果、键盘与桌面原划词行为。Release 构建成功，118 项 core 测试无失败，同证书签名核对通过。没有实机安装及外部 Moji 辞書启动验证。

以正式 1.1.12 为资源基线，仅替换本次 3 个界面资源、增加 6 张原图及定向的 Android 辞書打开接口。保留此前辞书减字和焦点修复，未更新 PC 客户端或修改活动文库，没有数据迁移或手工备份。安装包为 `dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-1.1.13-release.apk`，code36。发布核对在 `build/qa/moji-card/release-check.json`，页面检查记录在 `logs/moji-card-packaged.log`。
