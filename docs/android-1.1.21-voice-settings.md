# 1.1.21：手机声线选择与音源编辑

朗読の音声改为紧凑列表，行高从 105px 收紧为 61px。同一行放试听、名称／选中标记和更多操作；修改、删除移入操作菜单，添加放在标题旁。系统、在线及保存音声分组，系统项固定置顶且不能隐藏或改名。试听某一条在线声线不会更改当前选择，参考声线仍播放其真实 WAV 文件，关闭面板停止试听。

新增 Android TextToSpeech 的「システム音声」，使用手机当前文字转语音引擎的日语音声，复用原 start／done／error／stop 回调、语速和停止流程，长文本分段。按 Android 官方接口增加 TTS 服务可见性声明；未安装或未启用日语音声时报告不可用，不能当作播放成功。实现依据：[TextToSpeech](https://developer.android.com/reference/android/speech/tts/TextToSpeech)、[UtteranceProgressListener](https://developer.android.com/reference/android/speech/tts/UtteranceProgressListener)。词典即时朗读选择系统音声或圭太／七海；PC 模型与参考声线仍只用于已保存音频，没有在 Android 增加 Irodori 合成。

添加和修改都支持文件／音声URL；修改在线声线时可保留原声线、改名，或用文件／URL保存为参考声线。既有在线声线 ID 保留在可恢复目录，新参考音声持有独立稳定 ID。公开 HTTPS 网址经现有 PublicHttpClient 的 TLS、公开 DNS、重定向、网络策略、超时和 20 MiB 限制下载，再校验完整 WAV 及 1–120 秒长度；下载或校验失败不改已有声线。参考音频重命名和替换沿用现有存储接口。

137 项 Android core 测试通过（其中新增的 3 项已先观察到失败）；应用 Debug 编译、Release 构建／Lint、JavaScript 语法检查及同证书签名验证通过。375／390px 使用待打包资源和隔离 API 样本检查了实际点击目标、试听请求、系统选择、词典发音回调、URL 失败恢复、文件／URL替换、添加及删除。1440px PC 设置布局与 1.1.20 对照一致，无横向溢出或脚本错误。系统朗读回调及 URL 导入的交互在离线样本中验证，未连接手机实播或下载真实外网音频，不能据此宣称用户手机引擎已可用。

以正式 1.1.20 APK 的资源为基线，只替换 index.html、main.js 中的手机提示及 mobile-app.js／CSS，共 4 项前端资源；33 项界面／词典打包资源与检查输入一致，原始词典不变。未更新 PC 客户端、修改正式文库、迁移或创建备份。证据位于 `build/qa/mobile-voice-redesign/`，构建日志位于 `logs/mobile-voice-redesign-release.log`。

交付：`dist/FujimiShinbunBunkoAndroid/FujimiShinbunBunkoAndroid-1.1.21-release.apk`，code44，可覆盖安装。73,765,460 字节，SHA-256 `c6ee6f6b5e8153a8896a9e6a83b845a10f558014515df5c2e931afc6a1e04ac2`。
