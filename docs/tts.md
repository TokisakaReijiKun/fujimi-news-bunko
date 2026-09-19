# Irodori 本地朗读

`tts_integration.py` 装配接口、设置和文件存储；`tts_service.py` 管理声线文件、持久任务与单个 FIFO 队列；`tts_worker.py` 在 Tokyo 子进程中运行上游推理接口。普通 `create_app()` 不启用模型，命令行入口独占绑定端口后才创建启用 TTS 的应用。测试通过 `tts_backend` 注入合成后端。

推理配置与本机 `Irodori-TTS/JKL.py` 对齐：主模型和 DACVAE 均使用 `cuda:0` / `bf16`，codec 明确加载 `model/Semantic-DACVAE-Japanese-32dim/weights.pth`。采样使用 40 步、text CFG 3、speaker CFG 5、最长 30 秒，第一段 seed 42，后续按编号递增。此前 Web 的 CPU / FP32 codec 路径会产生很大的系统内存峰值，已移除。整段输入、编号续跑与完整音频复用规则保持一致。

普通主模型和 DACVAE 在 CPU 上先转换到目标精度，再搬到 GPU，避免先创建完整 FP32 显存副本。主模型转移完成后释放 checkpoint 状态字典，再加载 tokenizer 和 DACVAE，以减少加载期间存活的 CPU 权重引用；工作进程就绪前归还不用的 CUDA 初始化缓存。量化主模型保留原有转换路径。五分钟空闲复用规则保持不变。加载子进程意外退出时只自动重试一次；明确的模型加载错误、取消和 300 秒加载超时不自动重试。日志使用无缓冲输出，记录启动时间、PID、加载阶段、就绪及退出码，区分原生崩溃与超时。此优化不保证在系统提交内存耗尽时仍能生成成功。

## 使用与状态

新闻仅在验证、来源后处理和保存成功后排队，音频不参与新闻配额或日刊终态。文本导入同样自动排队。书籍仅处理用户选中的章节；标题和非空日文块依阅读顺序朗读，ruby 注音和图片本身不作为额外文本。模型不生成中文译文音频。

任务状态为 `queued/running/completed/failed/cancelled/interrupted`，阶段包括 `queued/loading/tts/merging/saving/complete`。每个自然段优先整段合成，只有 tokenizer 计数超过 `min(256, 模型文本上限)` 才按原句界、逗号和 token 上限拆分。`split_text` 的兼容参数名 `max_chars=256` 在这里表示 token 预算，不按 Unicode 字符数截断。计数以实际合成单元为单位，合并后的时间表仍对应原文段落。全部单元按顺序流式拼接为 PCM16、48 kHz、单声道 WAV；完成必须意味着完整 WAV 已验证、附件已登记并提交。

运行任务取消后，当前分段可能仍在计算，但结果不会提交；新任务在其退出后依次执行。新闻和书籍片段都直接原子保存到各自音频目录的 `<声线名>_<标题>_segment_01.wav` 等文件；书籍不再按章节 ID 建立分段子目录。重试从连续存在且格式有效的编号片段之后继续，例如已有 `01` 至 `05` 时从 `06` 开始，不再维护 segment manifest。完整音频提交成功或检测到该声线已有完整音频后，删除该前缀的全部编号片段和旧 manifest；失败或取消时保留片段供下次续跑。

任务状态只保存在当前服务内存中。任务拼接目录和模型进程通信目录使用系统临时目录，任务结束或服务关闭时清理。项目不创建 `data/tts`，也不把 TTS 临时文件写入 `data/diagnostics`。服务重启后不显示旧任务历史，但文章和书籍目录中的未完成编号片段仍可继续使用。模型空闲五分钟退出；依赖或 CUDA 不可用会明确报错。日志在 `logs/tts-worker.log`。

声线文件不使用 `voices.json` 或 ID 子目录：`data/voices/<声线名称>.wav` 是唯一事实来源，服务从该目录扫描声线。API 保留 JavaScript 安全范围内的数值 ID 兼容现有前端，但 ID 由名称稳定推导；改名时会同步全局、来源、文章和章节引用。旧版 `voices.json` 布局会先备份到 `data/backups/voice-storage-layout-*/`，再一次性平铺迁移。

完整朗读优先按正文和声线复用，并校验登记、文件哈希、WAV 格式和段落时间。文章和书籍完整音频都使用 `<声线名称>_<标题>.wav`，直接放在各自的 `audio/` 根目录；同名章节或旧版本冲突时追加稳定哈希后缀。对应文件和登记有效时直接加载，不启动模型。服务初始化会把书籍旧的 `audio/<章节 ID>/<任务 UUID>.wav` 迁移到新命名，先备份书籍目录和索引；迁移失败保留原文件和登记。切换声线再切回时，可从新闻附件的 `tts` 元数据或章节 `audio_versions` 找回已有音频。更换模型不会使完整朗读失效，也无需加载模型来复用；正文或参考音频变化、文件缺失或损坏才重新生成。旧客户端的 `force=true` 不再绕过有效朗读。

新生成新闻的完整音频由 ArticleStore 管理；过长或 Windows 禁用字符会安全截断／替换，同名旧音频仍存在时追加摘要。新闻 TTS 以新 WAV 先落盘、`article.json` 最后原子替换为提交点，不移动整篇文章目录，因此 Windows 播放器持有旧 WAV 时也能切换或复用朗读。失效且已不再引用的旧音频登记会先连同文章目录、SQLite 索引备份到 `data/backups/tts-article-*/`，再移出活动清单。当前仍引用的附件和新闻图片校验不会跳过。提交使用最新文档，正文变化时拒绝旧结果，保留收藏、阅读进度、书签和已有译文。

## 接口

| 接口 | 行为 |
| --- | --- |
| `POST /api/articles/<id>/tts` | 按 `mode`、`voice_id` 生成或复用缓存 |
| `POST /api/articles/<id>/reread` | 同上，有效同声线朗读直接复用 |
| `DELETE /api/articles/<id>/tts` 或 `/reread` | 只取消该文章的音频任务 |
| `POST /api/books/<bid>/chapters/<cid>/reread` | 章节生成或复用，兼容 `force` 但优先复用 |
| `PUT /api/books/<bid>/chapters/<cid>/voice` | 保存章节声线选择 |
| `GET /api/tts/tasks` | 返回当前服务内存中的任务列表 |
| `GET/DELETE /api/tts/tasks/<id>` | 查询或取消当前进程任务；兼容 `/api/books/tasks/<id>` |
| `GET /api/books/<bid>/audio/<path>` | 授权音频读取，支持 HTTP Range |
| `GET/POST /api/settings/voices` | 列出声线、上传文件 |
| `PUT/DELETE /api/settings/voices/<id>` | 改名、更换文件、归档删除 |
| `POST /api/settings/voices/from-url` | 下载并验证公开网址参考音频 |
| `PUT /api/settings/voices/<id>/from-url` | 从网址替换音频 |
| `PUT /api/settings/active-voice` | 选择全局声线、浏览器或关闭 |

`model` 和来源设置的 `inherit` 均解析为当前全局声线，`voice` 使用指定参考音频，`browser/none` 不提交模型任务。生成响应包含 `task_id` 和 `status`；缓存命中为 `status=ready`。新闻的 `audio_path/audio_segments`、章节的 `audio.url/audio.segments` 保持原有字段。新闻附加 `audio_task_id/audio_task_status`，章节附加 `audio_task`，用于刷新后恢复任务反馈。

健康接口保留字符串 `tts` 并增加 `tts_details`：`configured` 仅表示主模型文件存在，`inference_verified` 表示本次服务生命周期实际合成成功过，`state` 表示加载状态，`error` 给出失败信息。不能将 configured 当作生成成功。

## 验证

自动回归使用临时数据、合成参考音频和 FakeBackend，不调用真实模型或付费 API：

```powershell
conda run -n Tokyo python -X utf8 -m unittest discover -s tests -v
node --check static/main.js
node --check static/book-reader.js
```

真实模型和页面验收使用独立临时文库，不启动日刊调度或加载个人 `.env`：

```powershell
conda run --no-capture-output -n Tokyo python -X utf8 scripts/verify_tts.py --port 8428
```

快速真实模型验收可运行 `conda run --no-capture-output -n Tokyo python -X utf8 scripts/verify_tts.py --smoke`：两段正文（第一段有多句话）应只生成两个单元，检查完整 WAV 时间表、HTTP Range 和同声线复用后退出，并保留临时文库供检查。

此命令打印临时目录，创建一篇短新闻及带正式目录、ruby、插图和长段落的 EPUB；新闻自动生成，章节通过现有界面生成。检查音频可解码、播放时间递增、段落跳转、取消／重试、刷新恢复、375/390px 布局，并试听发音。临时文库保留供检查，可在停止验收服务后自行移除。
