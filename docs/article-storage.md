# 新闻文件格式与恢复

数据库直接位于 `data/fujimi.sqlite3` 和 `data/dictionary-search.sqlite3`，不再使用 `databases/` 子目录。已有子目录布局可在停服务后使用迁移工具 `--apply` 搬回根目录，工具会先备份且拒绝覆盖同名目标。旧正文存储通过表中是否存在 `payload` 判断，不再根据数据库是否位于根目录判断。

## 布局

`data/articles/日刊日期/创建时标题/` 下：

| 文件或目录 | 用途 |
| --- | --- |
| `article.json` | schema_version=1；文章 ID、标题、URL、来源、状态、收藏、日刊归属、文本区间与媒体登记 |
| `original.txt` | UTF-8 原文，以两个 LF 分隔段落 |
| `translation.txt` | UTF-8 译文；空段由区间表示，未翻译时为空 |
| `furigana.html` | UTF-8 假名段落，阅读器按区间读取 |
| `media/` | `image-001.jpg` 等图片与 `video-001.mp4` 等视频，篇内独立存放 |
| `audio/` | TTS 预留。将来按声线与参数指纹分目录；迁移旧音频归入 `legacy/` |

同一 URL 在同一天重复导入时复用当天文章；跨日期再次导入时分配新的文章 ID，并在对应日刊日期目录保存独立正文、媒体和音频。日刊归属为 `edition_dates` 数组，新的按日副本通常只包含自身日期。目录创建后不因标题修改而移动。Windows 禁用字符替换为下划线，保留名称加前缀，重名追加 ID；标题过长时截断并附 ID，完整标题始终在元数据中。

收藏文章时，将其完整目录复制到 `data/bookmarks/创建时标题/`。收藏副本不进入新闻索引；取消收藏时删除该副本，`data/articles/` 中的日刊文章保持不变。

## 文件与索引

`article.json.article` 不含段落正文。`text_files` 按文件记录 SHA-256、段落字段名和 `[start,end]` 区间（Unicode 字符下标，左闭右开）。原文及全文译文表示通过 `whole_span` 保留；少数旧数据的全文表示与段落拼接不同，会额外保留其文本区间，保证迁移不改变内容。

`assets` 保存相对路径、kind、SHA-256、字节数、旧链接映射及可用的图注、原链接、原媒体 URL、段落位置。每篇拥有独立的媒体副本。正文 API 返回可访问的附件 URL，磁盘文件仅使用相对路径。只允许访问已登记的 `media/`、`audio/` 文件；禁止直接下载元数据、TXT 或任意路径文件。

`data/fujimi.sqlite3` 中：

- `articles`：ID、按 URL 与日刊日期生成的唯一键、目录、标题、来源、状态、收藏、采集时间、修订号，无正文 payload。
- `article_days`：文章与所属日刊日期的关系；保留旧数据的多日期兼容能力。
- `article_sequence`：ID 分配，不因新闻索引清空而回退。
- `books`、`settings`：仍是业务数据，不能作为缓存删除。

启动和“文庫刷新”读取文章目录重建新闻索引。任何文本校验错误、附件缺失、重复 ID/URL 都会使整次索引替换停止，并写入 `data/diagnostics/reports/article-index.json`。运行时读取正文始终读取文件，不回退到旧数据库正文。

## 写入与异常恢复

存储层使用进程内锁与数据根目录文件锁，序列化读写及修复操作。修订号用于拒绝过期写入，避免翻译任务覆盖更新后的收藏或正文。

更新先在 `data/diagnostics/transactions/<transaction>/new/` 构建完整目录，校验文本及登记附件后写入 `journal.json`。原目录重命名为事务内 `old/`，新目录随后切换到文章位置，最后更新索引。

- 切换前中断：恢复旧目录。
- 目录切换成功后中断：从已提交文件更新索引。
- 索引不可写：保留恢复日志，后续操作或启动时重试；不读取过期正文。
- 手工改动 TXT 导致校验失败：报告不一致，不猜测译文对应关系。

正常提交后清理事务临时副本。应用只提供本地单实例服务；迁移和回滚仍必须停服务执行。

## 迁移与回滚

```powershell
conda run -n Tokyo python -X utf8 scripts/migrate_storage.py
conda run -n Tokyo python -X utf8 scripts/migrate_storage.py --apply
conda run -n Tokyo python -X utf8 scripts/migrate_storage.py --rollback
```

默认预览不写数据。可用 `--data-dir` 指定目录，默认采用 `FUJIMI_DATA_DIR` 或项目 `data/`。

迁移备份位于 `data/backups/storage-migration-<时间>/`。`original/` 保存切换前数据库及原目录数据；`retired/` 归档已退出使用的旧数据库、共享媒体；`migration.json` 记录备份、构建、验证、切换、归类及完成阶段。执行中断后再次 `--apply` 会继续，完整迁移再次执行不重复导入。

迁移保留文章 ID、收藏、原文、译文、假名、状态和历史日刊关系，并核对附件哈希、书架和设置。付费记录维持已清空正文的排除状态。未知文件不移动，列入迁移报告。迁移不触发采集、翻译或音频生成。

回滚先将新文章树、数据库和诊断数据保存在迁移备份的 `rollback-<时间>/`，再复制恢复原布局。回滚后需要使用迁移前服务代码；新版服务会拒绝直接启动旧根目录数据库，防止产生两个事实来源。

文章修复工具的备份也包含选定文章目录，不能再只备份 SQLite。完整灾备请停止服务后复制整个 `data/`；密钥仍单独保存在被忽略的项目 `.env`，不混入新闻目录。
