# 富士見新聞文庫

富士見新聞文庫是一款正在开发和交付的本地新闻与日语阅读产品，提供 Web 应用和 Windows 桌面端。项目以新闻来源、阅读体验和用户提供的参考素材为输入，在本地实现采集、翻译、书架、词典和朗读能力；参考素材不是产品边界，也不代表所有功能都必须复制其行为。

## 启动（conda Tokyo）

在本项目目录打开 PowerShell：

```powershell
conda activate Tokyo
python -m pip install -r requirements.txt
python -X utf8 server.py
```

浏览器打开 **http://127.0.0.1:8427**。也可以运行 `./start.ps1`；该脚本使用 `conda run -n Tokyo`。修改端口：`./start.ps1 -Port 8428`。

Windows 桌面窗口默认使用 8428 端口，可用 `./start-desktop.ps1` 启动；先运行 `conda run -n Tokyo python -m pip install -r requirements-desktop.txt`。要制作独立程序，运行 `./build-desktop.ps1`。项目内的桌面程序可使用现有 Tokyo 环境与 Irodori 模型，显示并使用 `data/voices/` 中的声线；详见 [Windows 桌面客户端](docs/desktop-client.md)。

## 下载与发布

正式版本发布在 [GitHub Releases](https://github.com/TokisakaReijiKun/fujimi-news-bunko/releases)。Windows 用户下载带有 `windows-x64.zip` 的附件，解压后运行其中的 `FujimiShinbunBunko.exe`；该包是便携式桌面程序，不包含用户的 `data/`、`.env`、日志或 Irodori 模型。运行需要安装 Microsoft Edge WebView2 Runtime。桌面程序移出项目目录后，会把用户数据保存到 `%LOCALAPPDATA%/FujimiShinbunBunko/data/`。

当前实现无需 Node 构建步骤。服务器默认只监听本机，运行终端中按 Ctrl+C 停止。自动日刊仅在服务运行时检查 CST 时间；关机期间错过的任务不会补跑。后台启动的进程号记录在 `logs/server.pid`，日志位于 `logs/`。

## 已实现

新闻采集和后处理已按六家来源拆分到 `news_providers/`。每家独立维护链接收集、正文解析、媒体规则、后处理顺序和重新翻译；公共层仅保留单项基础服务。详见 [分来源新闻处理](docs/news-providers.md)。

- 本日新闻：六家官网新闻列表及 RSS/Atom/RDF 来源、手动生成、CST 定时生成、日期切换、任务状态与停止后续采集。
- 阅读室：网址导入、粘贴日文正文、离线假名、Irodori 本地音频与浏览器日语朗读、翻译显示切换、选词查词、复制。
- 收藏：文章收藏与取消，文件持久化、SQLite 索引。
- 书架：多 EPUB 导入、重复检测、封面、系列、元数据编辑、章节目录、横排／竖排、进度恢复、段落书签、章节假名处理、删除书籍记录。
- 词典：内置 **159,396** 个词条，支持日语／假名／常见罗马字／中文释义搜索、释义与例句、查询历史。Tokyo 的 SQLite 不支持原词库所用 FTS4，因此首次启动会建立独立的搜索索引，词库文件不被修改。词典文件约 304 MiB，因 Git 托管平台的单文件限制未纳入本仓库；从源码运行前请将 `dictionary.sqlite3` 放回 `apk-original/dictionary/`。
- 设置：参考声线上传／网址导入／管理、浏览器声线、新闻来源与最低数量、日刊数量与时间、书架排序、SQLite 整理。
- 桌面侧栏、手机抽屉导航、键盘焦点、减少动画偏好。

首次运行不生成或冒充真实新闻。阅读室的“填入示例”是明确标注的操作例文。可以从设置生成日刊，或导入自己需要的文章与 EPUB。

阅读室示例保存到 `data/articles/examples/<标题>/`，标题、正文和声线偏好由本地服务共享。“阅读声线”可选择默认、浏览器日语声线或现有模型声线；同名保存先备份再更新。旧浏览器示例会在打开服务页面时备份并迁移，详见 [示例存储与迁移](docs/reading-examples.md)。

默认新闻来源包含六家媒体，设置页显示官网地址：

| 来源 | 官网 |
| --- | --- |
| NHKニュース | https://news.web.nhk/newsweb/ |
| 朝日新聞 | https://www.asahi.com/ |
| 読売新聞 | https://www.yomiuri.co.jp/ |
| 日本経済新聞 | https://www.nikkei.com/ |
| 産経新聞 | https://www.sankei.com/ |
| Yahoo!ニュース | https://news.yahoo.co.jp/ |

旧版 NHK 官网 `https://www3.nhk.or.jp/news/` 现跳转到上表地址。升级会一次性修正旧 RSS 网址并补齐五家来源，保留已有来源 ID、最低数量、声线与自定义来源；旧配置保存在 SQLite 设置项 `news-sources-before-homepages-v1`。之后的自主编辑与删除不会在重启时被覆盖。官网链接发现通过验证不代表每一篇付费／登录文章都能导入。

## 翻译与朗读

Irodori 使用本地 `Irodori-TTS/model/model.safetensors`，由 Tokyo 启动受控推理子进程。默认参考声线为 `朽木冬子.mp3`，模型在 CUDA 上采用 BF16，音频编解码在 CPU 上运行。首次加载需要等待；单队列依次处理新闻和章节，空闲 5 分钟后释放显存。GPU、codec、tokenizer 和水印依赖须已在本机准备好，运行时不自动下载模型。

新新闻保存后自动生成朗读，正文可立即阅读；书籍从“読書設定”按章节生成。音频保存为 48kHz 单声道 WAV，支持暂停、拖动、倍速和段落定位。中止后当前分段返回即退出；重新生成失败保留旧音频。任务跨页面可查询，服务重启后未完成任务标记中断，需要手动重试；历史文章不会批量补生成。默认声线可以切换回浏览器或关闭，不会在模型失败时自动改用其他声线。

首次启用会先将 SQLite 和相关设置备份到 `data/backups/tts-settings-*/`，再注册冬子并让六家默认来源沿用全局声线。参考音频支持 1–120 秒、20 MB 以内的 WAV、MP3、FLAC、OGG、M4A；M4A 解码需要本机 `ffmpeg`。声线保存为 `data/voices/<声线名称>.wav`；替换会覆盖同名声线文件，改名会同步改名，删除前会归档。新闻音频保存为每篇文章 `audio/<声线名称>_<新闻名称>.wav`。详见 [TTS 接口与验证](docs/tts.md)。

浏览器朗读依赖系统／浏览器安装的日语语音；部分在线语音需要网络。假名由 pykakasi 离线生成，多音字和人名读法可能需要校对。

可选 DeepSeek 翻译配置：在当前进程环境设置 `DEEPSEEK_API_KEY`，或在项目 `.env` 中保存 `DEEPSEEK_API_KEY=你的密钥`。`server.py` 启动时自动读取本机配置，环境变量优先；`.env` 已被 Git 忽略，密钥不写入网页、SQLite 或源码。可用 `DEEPSEEK_MODEL` 指定模型，当前本机配置为 `deepseek-v4-flash`。设置密钥后，网址导入、文章重新翻译和章节处理会将相应正文发送给 DeepSeek，可能产生 API 费用。未配置时不发起翻译请求，保留原文和假名。粘贴导入默认只在本地处理。

日刊最低配额按成功收录数核算，失败时会尝试同来源后续文章；重试生成会优先补齐当日缺失来源。数量或来源不足时显示“部分完成”，不会显示 100% 完成。已完成的文章保持不变；如果已有条数达到目标但来源缺失，补齐可能使总数超过目标。非文章重定向页面不会进入日刊。

日刊先由每个来源独立验证最多 5 个公开候选，会员、无效和错误分页候选在此阶段排除；随后先从六个来源各选 1 篇，再从剩余公开候选中随机补足每日目标，最后只对入选的新文章执行来源自己的翻译和媒体后处理。状态区分别显示候选、选择、后处理、翻译与媒体保存；会员标记在来源列表解析时排除（包括锁图标 alt/aria-label 和重复链接）；正文仅保留防漏标校验，不作为“未收录”错误。网页请求使用连接／读取超时，正文、翻译和媒体阶段另设等待预算。中止后，当前网络请求返回即退出，旧任务不会向新任务写入状态或文章。

若已配置 HTTPS 代理而本地 DNS 返回非公网地址，采集器通过 Google DNS-over-HTTPS 独立验证该域名的公网记录，再由代理连接官网；无代理时不使用此回退。localhost、私网 IP 和解析到私网的目标仍被拒绝，TLS 校验保持开启。

产品源码、DeepSeek 密钥和 Irodori 权重分别按源码、用户配置和本地运行时管理。Irodori 已通过本地推理代码接入；**Android/Windows 双向同步和 Android 后台服务仍未接入**。模型权重和上游 `Irodori-TTS/` 代码保持原样。

新闻解析支持公开的静态 HTML 正文与 RSS/Atom，跳过推荐链接、分享提示和署名；有付费／会员限定标记的文章不会收录。Yahoo 按正文段落与同一文章分页提取，遇到缓存页、错误重定向或未知正文结构时停止，不保存不完整正文。需要登录、订阅或客户端渲染的文章可在原站阅读。

正文图片、图注和段落位置会保存到 `data/articles/首次采集日期/标题/media/`，阅读器通过按文章 ID 分配的附件接口显示；直接公开的 MP4/WebM 视频也可缓存。单篇上限 30 张图片、5 个视频、单文件 32 MB。动态播放器、HLS 和 DRM 视频暂不下载，界面会说明已保存预览图或媒体失败，用户可跳转原站观看。不会将预览图标记为已下载视频。EPUB 支持常见图片和 ruby，支持 SVG 包装的栅格封面；复杂固定排版、嵌入字体、动态 SVG 和 DRM 不支持。任务取消停止后续步骤，进行中的网络请求可能继续完成。

## 文件结构

```text
server.py                    Flask 服务、词典、新闻、EPUB、任务与定时器
article_store.py             文件为主的新闻存储、事务恢复、SQLite 索引
storage_migration.py         旧存储迁移、校验及回滚
scripts/migrate_storage.py   只读预览／执行迁移／回滚入口
news_sources.py              默认来源、配置迁移与来源分发兼容入口
article_extraction.py        解析兼容入口，转交来源模块
news_providers/              六家独立采集、解析、后处理与重新翻译
article_media.py             经过格式校验的图片与直接视频本地缓存
scripts/repair_articles.py   指定文章的备份、重新提取和付费记录隔离
static/index.html            桌面 Web 页面入口
static/main.js               主交互、浏览器适配、播客播放器与进度恢复
static/static.css            主样式、布局与浏览器适配
static/book-reader.js / book-reader.css  EPUB 阅读器适配
static/player_assets/        播放器图标资源
apk-original/               参考素材、只读词典和 Android 设置页（词典文件需另行放置）
data/fujimi.sqlite3          新闻、书架索引与设置（运行时创建）
data/dictionary-search.sqlite3  可重建的词典查询索引
data/books/                 书名目录：原文件名.epub、book.json、state.json、chapters/、resources/、audio/
data/articles/              每篇新闻的正文、译文、元数据、media/ 与 audio/
data/backups/               迁移及修复备份
data/diagnostics/           检查文件、重建报告、事务恢复日志
docs/apk-manifest.json       参考包与提取资源 SHA-256
tests/test_web.py            功能、持久化、导入及边界测试
start.ps1                   Tokyo 启动脚本
```

备份个人数据时先停止服务，再复制整个 `data/`。应用内删除书籍会先将完整书籍目录归档到 backups，再移除书架索引。参考包、`apk-original/` 与现有 `Irodori-TTS/` 均保留。

如果在文件管理器中删除 `data/books/书名/`，点击设置中的“存储を反映”会清理失效索引并更新书架。书籍正文、进度与书签现在保存在目录中；删除整个目录后，数据库只能恢复残留的索引信息，不能恢复已删除的文件。无插图 EPUB 同样保留原文件和完整书籍目录。

更正已有采集结果可使用 `conda run -n Tokyo python -X utf8 scripts/repair_articles.py --ids 文章ID` 预览；加 `--apply` 才执行。脚本先备份 SQLite 和选定文章目录，再按原 URL 重新提取，保留 ID、日期与收藏；复用未改变段落的译文，补译变化段落。付费记录标记为 `excluded_paid`，正文从阅读接口移除，修复前内容留在备份中。历史日刊因剔除付费文章而变少时会如实显示来源不足，不用当前日期的文章冒充历史新闻。

## 验证

服务在 Windows 使用独占端口绑定，避免两个服务同时监听 8427 而让旧采集逻辑继续响应。只有绑定成功后才写入 `logs/server.pid` 并启动日刊定时器；重复启动会退出，已有服务不受影响。

```powershell
conda run -n Tokyo python -X utf8 -m unittest discover -s tests -v
node --check static/main.js
node --check static/book-reader.js
```

测试使用临时数据库和自行创建的 EPUB/新闻样本，不访问个人文章或真实网络；覆盖词典、罗马字、持久化、收藏、EPUB 顺序、危险 HTML 清理、章节进度、假名处理、RSS 导入、输入校验及缺少外部服务时的错误说明。浏览器另行检查桌面与 390px 手机布局。


## 新闻文件存储

数据库直接放在 `data/` 根目录：`fujimi.sqlite3` 和 `dictionary-search.sqlite3`，不使用 `databases/` 子文件夹。之前版本创建的子文件夹可通过下方迁移工具 `--apply` 备份后搬回根目录，文章目录不变。

新闻按 `data/articles/YYYY-MM-DD/标题/` 保存，目录日期是首次采集日（CST），与以后收录到哪些日刊分开。目录名只在创建时确定，重名时追加 ID；改标题不搬目录。每篇包含 `article.json`、`original.txt`、`translation.txt`、`furigana.html`、`media/` 和 `audio/`。

正文和译文文件是内容来源，`article.json` 记录段落字符区间、校验值、日刊归属、收藏和附件信息。数据库的新闻表不再保存正文 `payload`；可通过设置中的“文庫刷新”重建新闻索引。数据库仍保存应用设置，不能直接删除整个数据库；书架索引可从有效书籍目录重建。不要只修改 TXT 而不更新元数据：检测到校验不一致时系统会报告异常，不会继续显示可能错位的译文。

图片和视频都在文章的 `media/` 内，不依赖全局共享目录。文章 `audio/` 保存本地 Irodori 朗读 WAV；旧媒体 URL 仍通过文章元数据中的兼容映射读取。

迁移工具默认只读预览，执行或回滚前停止本地服务：

```powershell
conda run -n Tokyo python -X utf8 scripts/migrate_storage.py
conda run -n Tokyo python -X utf8 scripts/migrate_storage.py --apply
# 回滚：先保存当前新结构，再恢复迁移前布局；随后需使用迁移前版本的服务代码。
conda run -n Tokyo python -X utf8 scripts/migrate_storage.py --rollback
```

`--data-dir` 可指定独立数据根目录，默认遵循 `FUJIMI_DATA_DIR`。迁移不联网、不重新翻译。详见 [存储格式与恢复说明](docs/article-storage.md)。


## 书架新版

书架采用按书独立文件存储、EPUB3 nav／EPUB2 NCX 正式目录和段落锚点。保留原 EPUB，章节与阅读状态分开写入；修复双语原序、插图与既有阅读模式的显示。详见 [书架与 EPUB 阅读器](docs/book-reader.md)。
