# 手机文章点词查词实施清单

**目标：** 用户已选定仅移植 Moji 的点词直接查词。点击正文或其假名，短暂高亮正文词语，并在底部显示词典释义；复用现有本地词典、发音和词条详情。

**依据：** 提供的 APK 中 `MOJiArticleDetail-121467f1.js` 的 `clickContentResponse`、`.on-click-word` 样式，以及 `layout_reader_word_dialog` / `reader_word_expand_dialog_layout`。前者确认 ruby/rt 查询正文和 500ms 高亮；后者确认底部面板、20px 词头、读音及发音／详细查询入口。静态分析使用 APK 脚本、aapt2 和 apkanalyzer，未依赖 Moji 网络接口。

**实现：** 在 `static/main.js` 的手机标记内接入正文分词和点词事件，保留 ruby，避开链接及播放器操作；复用已有查询异步取消和结果渲染。`static/mobile-reader.css` 只为该模式提供底部面板样式。数据、词库和 PC 客户端不变。

- [x] 写点词、假名、连续快速点击及返回关闭的失败测试。
- [x] 实现手机文章入口和底部释义，核对鼠标／触摸／键盘事件不触发段落播放。
- [x] 在 375/390px 检查真实页面、溢出与图片；在桌面检查原有选择查询和样式不变。
- [x] 依 review-agent 对最终改动进行只读检查，不委派该审查。
- [x] 构建同签名手机安装包并核对打包资源。
