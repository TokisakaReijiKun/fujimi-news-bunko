# Android 1.0.17：播放器恢复与菜单遮挡修复

返回缓存章节时恢复对应播放器；在新闻与书籍之间切换后，如果原控制器已停止，只重新建立音频控件，不重建正文。新闻翻译模式、书籍已展开的译文和正文事件保持有效。恢复前撤销旧的段落跳播及菜单事件，避免一次点击触发旧控制器。

切换阅读视图时暂停音频，Android 同步本地暂停状态。直接打开新闻跳过旧文章恢复，避免额外请求旧音频。播放器层级设在导航栏之上、抽屉遮罩和菜单之下，关闭菜单后仍可操作播放器。沿用原有界面和播放功能。

## 验证

- `verify_player_navigation.cjs`：375、390、1440px 共 8 组通过，覆盖 HTMLAudio、Media3 接口替身、浏览器语音替身、设置往返、新闻与书籍互切、正文状态保持、菜单遮挡与焦点恢复。HTMLAudio 使用可解码的合成 WAV；恢复后原生跳段只提交一次正确文章的请求。
- `verify_reader_type_player.cjs --player-only`：18 组通过，包含播放、暂停、拖动、前后段、倍速和高亮。
- `verify_audio_paragraph_boundary.cjs`：6 组通过，每组连续跳段 20 次。
- `verify_android_frontend.cjs`：5 组通过，包含 375、390、812px 移动布局与桌面。
- Tokyo `python -X utf8 -m unittest discover -s tests -v`：35 项通过。
- 三个正式 JavaScript 文件、新增回归脚本的语法检查及 `git diff --check` 通过。
- 只读代码复查与合成 Media3 页面连续往返 5 次通过，未发现遗留的旧控制器请求。

`verify_android_audio_ui.cjs` 未全部通过：其 Toast 避让断言失败。另以 HEAD 原版页面和本轮页面分别核对，二者均为 Toast 底边 818px、播放器顶边 814px，属于已有的约 4px 重叠。未扩大修改到这项既有布局问题。基线对照保存在 `build/qa/player-navigation/toast-baseline.json`。

本轮没有连接实体手机或运行 Android 模拟器。原生播放桥在浏览器回归中使用替身，不将其作为真实 Media3 解码或手机安装验收。

## 交付

- `dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-1.0.17-release.apk`
- 版本：1.0.17，versionCode 18；Release 构建和 APK v2 签名验证通过。
- 包内 20 项正式前端资源与当前源码逐字节一致。
- SHA-256：`ab41de8b332d61bcdf4228eb5dea0b9e0b42b5d2ed657401188ac79bef9d9909`
- 检查结果及页面截图：`build/qa/player-navigation/`。

没有修改用户文库数据，没有迁移，也没有创建备份。

## 按用户要求回撤到 1.0.17

撤回 1.0.18 至 1.0.20 的正文共用渲染及布局改动。使用上述原版安装包恢复正式前端资源；书籍局部样式、页面入口、主脚本和主样式均恢复至 1.0.17，原有播放器修复保留。后续版本新增的合并测试、计划和交付文档一并撤回。

为允许覆盖已安装的较新版本而无需卸载，重新签发 `1.0.17-rollback` / versionCode 22。安装序号用于 Android 更新判断，功能与页面资源回到原版 1.0.17；原始 1.0.17 / code18 安装包保留原样。

- 覆盖安装包：`dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-1.0.17-rollback-release.apk`。
- SHA-256：`c2e2e0b230f2de74797007ee313e19a1a65610c958834f91fe6dd18bf006420b`。
- 包内全部 23 项 assets 与原版 1.0.17 逐字节对应的 SHA-256 一致，其中 20 项前端资源同时与恢复后的源码逐字节一致。
- 375/390/1440px 播放器及导航回归 8 组通过；三个正式 JavaScript 文件语法检查通过，Release 构建、版本号与 APK v2 签名校验通过，签名证书不变。
- 验证记录：`build/qa/rollback-1.0.17/release-verification.json`，构建日志位于同目录。

没有连接手机安装验收，没有修改用户文库数据，没有迁移或创建备份。
