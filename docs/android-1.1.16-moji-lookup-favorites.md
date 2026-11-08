# Android 1.1.16：收藏页面与原版点词代码

收藏入口仍在「辞書 → 收藏」，打开完整页面，具有返回按钮、词条列表与取消收藏操作。进入词条后返回收藏列表。沿用手机已有的 `fujimi-dictionary-favorites` 记录，无数据迁移。

点词直接使用用户提供的 Moji阅读 APK 中 `assets/h5hybrid/assets/MOJiArticleDetail-121467f1.js` 的 `st/ne/j/lt/at/se/le` 七个函数，函数体逐字核对一致，放在 `static/moji-article-lookup.js`。外围只绑定本文元素、朗读状态及本应用的词库接口。现有 ruby 补齐原代码要求的 rb 节点；没有 ruby 的文本通过原版所用默认 Kuromoji IPADIC 分词，按 surface 查询，不由 Intl.Segmenter 切词。

撤掉手机点词的 60 字判断、必须先取消选区的限制、四条候选菜单和前端结果排序。原版函数清除选区、对原词短暂高亮；朗读期间点击当前段落查词，点击其他段落定位播放。旧鼠标选区查询不再处理手机文章，避免它异步关闭刚打开的词卡。桌面仍走既有选区查询。

静态追踪证据在 `build/research/moji-lookup/`：`ArticleWebView$b.clickContent → ArticleWebView.A → widget.e.d → ac.o1 → lb.w1.a`。原版会请求 `v1/word/clickDetail`，网络失败后走 Realm 查询。该在线服务和 Realm 查询引擎没有搬入；本应用的 `/api/dictionary/clickDetail` 是本地 SQLite 适配，直接读取对应原词详情，不将前缀词冒充所点词。原版函数和分词库的复用不等于完整复用了 Moji 在线词库、搜索排序或原生弹窗类。缺少的词条仍会提示未找到。

验证：

- 核心 JVM 测试 122 项通过，含实际 IPADIC 的词界、活用表层和原文保持检查。
- 375/390px 正式页面检查通过：收藏页面、打开/返回/取消收藏、既有声线操作；点正文/假名、已有选区、快速换词、词卡详情与收藏、键盘、朗读定位与当前段查词。
- 桌面页面的原有选区查询回归通过。正式 APK 使用基于 1.1.15 的手机资源，保留两个未发布至手机的 PC 设置文案差异。
- 未在实体 Android 手机运行；本轮没有修改、迁移或备份用户文库，也没有更新 PC 客户端。

发布版本 1.1.16（versionCode 39），沿用原应用 ID 和发布签名。
