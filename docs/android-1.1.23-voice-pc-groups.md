# 1.1.23：声线层级对齐 PC

核对正式 PC 客户端 `_internal/static/main.js` 的 loadVoices、populateBrowserVoiceSelect 和当前源码：主列表先列一个浏览器音声入口，再逐项列出真实参考声线；浏览器入口内部统一选择系统声线、圭太／七海及 Kokoro／VOICEVOX。先前手机按在线／保存能力拆类与 PC 不一致，现取消该分类。

手机主列表改为一个「システム音声」入口，副行显示当前声线，其后只列参考声线。入口右侧箭头打开完整目录，目录按现有 API 顺序显示所有 browser ID，不按 saved_audio_only 重新分类；参考声线不混入这个目录。选中、试听、编辑和文件／网址保存沿用既有接口。选择目录的返回按钮、Android 返回及 Escape 均回到主列表。

375／390px 隔离页面检查通过：主列表与 PC 一样只有一个浏览器入口和真实参考声线，内部保留系统、Edge、Kokoro、VOICEVOX ID，且无在线／保存标题。实际点击目标、返回／Escape、试听调用、词典朗读调用、音源修改失败恢复、添加和删除均通过。1440px PC 设置布局及声线列表对照一致。使用合成样本，没有操作正式文库或执行真实手机、PC 合成及网络配对。

以正式 1.1.22 APK 为基线，仅更新手机 JS、CSS 与 index.html 的资源缓存版本；33 项界面／词典资源与检查输入一致。DEX、main.js 和原词典逐字节不变，保留 1.1.22 原生及远程朗读实现。JavaScript 语法、Release 构建／Lint、版本及同证书签名检查通过。未更新 PC 客户端、迁移用户数据或创建备份。

安装包：`dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-1.1.23-release.apk`，code46，可覆盖安装。73,771,060 字节，SHA-256 `fef9fbf52fbe5c987f7cf5863cde13859533ac73815d599e2868ea8e81ddb707`。证据在 `build/qa/mobile-voice-pc-groups/`。
