# 映作 Framecraft · AI 短剧拆解与再创作工作台

React + TypeScript + Vite + Ant Design 前端，FastAPI 后端，独立 Python Worker，支持 MySQL／SQLite，媒体保存在本地。当前工程已切换到独立本机 MySQL，并接入中科大公共模型服务。

## 已实现的操作链路

- 创建本地工程，上传 MP4／MOV 和可选 UTF-8 SRT；校验时长、大小与媒体内容。
- FFmpeg 预览转码、音轨提取、PySceneDetect 候选切分、镜头内关键帧采样。
- OpenAI 带时间信息转写、抽帧视觉分析、角色／场景／道具提取、故事结构分析。
- 分镜与播放器联动、关键帧导航、镜头编辑、证据回看、审核及不可变版本记录。
- 资产编辑、合并及引用更新；原片资产可在编辑弹窗中按镜头拆分。
- 设置新故事要求，生成并审核大纲，再生成剧本、分镜与新剧资产规划。
- 新剧资产按需生图；已有图作为编辑参考；图片替换与历史预览。
- 独立 Worker、任务心跳、检查点缓存、取消、显式重试、过期任务恢复、调用用量记录。
- 结构或证据校验失败时最多进行一次格式修复，分别记录实际请求；校验失败结果不作为有效缓存。
- 固定快照导出 Markdown、CSV、JSON、图片、审核记录与 SHA-256 manifest 的 ZIP。

**真实 API 尚未配置并验收时，界面不会生成模拟 AI 结果。** 自动化测试中的替身只在 tests 目录运行。火山剧创目前采用通用包人工迁移，未宣称平台直接导入兼容。

## 安装与启动（Windows PowerShell）

需要 Python 3.11／3.12、Node.js（建议 Node 22 LTS，满足当前锁定工具链要求）、npm。FFmpeg 可使用 imageio-ffmpeg 附带的二进制，无需系统安装；已有 FFprobe 时优先使用，否则通过 FFmpeg 解析媒体信息。

首次安装：

```powershell
.\scripts\setup.ps1
```

如需指定 Python：

```powershell
.\scripts\setup.ps1 -Python 'C:\Python312\python.exe'
```

开发模式，启动后在当前终端保持运行，Ctrl+C 停止本次启动的进程：

```powershell
.\scripts\start.ps1
```

访问 [工作台](http://127.0.0.1:5173) 与 [API 文档](http://127.0.0.1:18400/docs)。

构建后由 FastAPI 同源提供前端：

```powershell
.\scripts\start.ps1 -Production
```

访问 [本地构建版](http://127.0.0.1:18400)。此模式也只监听本机，不是互联网生产部署方案。

## 数据库配置与运行

当前实例为 MySQL Community Server 8.4.13 LTS，配置如下：

| 配置 | 值 |
|---|---|
| 地址 | `127.0.0.1` |
| 端口 | `13306` |
| 数据库 | `framecraft` |
| 应用账号 | `framecraft` |
| 字符集／引擎 | `utf8mb4` / InnoDB |
| 应用连接配置 | `.env.local` 中的 `DATABASE_URL` |
| 实例与数据目录 | `.runtime/mysql/` |
| 本地管理凭据 | `.runtime/mysql/credentials.json`，仅本地保存，不提交版本控制 |

应用账号仅有 `framecraft` 库权限，数据库只监听回环地址，不需要映射到花生壳。连接密码随机生成，不写进源码、前端、命令行参数或普通日志。`DATABASE_URL` 优先于分字段的 `MYSQL_HOST / MYSQL_PORT / MYSQL_DATABASE / MYSQL_USER / MYSQL_PASSWORD`；未配置这两种方式时使用 `DATA_DIR/studio.db`。

SQLAlchemy 使用 PyMySQL 驱动、连接健康探测、连接池回收及 READ COMMITTED 隔离级别。模型表已补齐字符串长度和 MySQL 字符集。SQLite 的条件唯一索引仅对 SQLite 创建；MySQL 使用生成列唯一索引保证每工程至多一个活动任务，已完成任务不占用这个唯一位置。

安装包已按官方页面的 MD5 校验后解压。MySQL 在本机不能正确使用中文配置路径，因此管理脚本在 `%LOCALAPPDATA%/Framecraft/` 下创建指向项目实例目录的 ASCII 目录联接；二进制与数据仍存放在 `.runtime/mysql/`，不要删除正在使用的目录联接或实例目录。

已设置 `MYSQL_LOCAL_MANAGED=true`，正常运行 `scripts/start.ps1` 会先启动此实例，再启动 API、Worker 和前端。退出工作台不会自动关闭 MySQL。管理命令：

```powershell
.\.venv\Scripts\python.exe scripts\mysql_local.py status
.\.venv\Scripts\python.exe scripts\mysql_local.py start
# 先退出工作台及 Worker，再关闭数据库
.\.venv\Scripts\python.exe scripts\mysql_local.py stop
.\.venv\Scripts\python.exe scripts\database_admin.py check
```

在另一台 Windows 机器首次创建同类实例：先安装项目依赖，执行 `mysql_local.py setup`、`database_admin.py init --local-mysql`，再按需要迁移数据，最后执行 `mysql_local.py activate`。`activate` 保留 `.env.local` 中其他配置，只更新数据库 URL 和本机管理标志。

### SQLite 数据迁移与回退

本次已迁移 2 个工程、31 条媒体记录、10 个当前实体、10 个版本、4 个任务和 9 条阶段记录。6 张表均比对了行数及按主键排序后的规范 JSON SHA-256。媒体文件不搬迁，数据库中的相对路径保持不变。

原始 `data/studio.db` 未修改，迁移前一致性快照及校验报告在 `data/backups/`。迁移工具要求目标表为空，不会覆盖已有 MySQL 工程；写入及核对在同一事务中完成。手动迁移方式：

```powershell
# 先等待任务结束并停止 API 与 Worker
.\.venv\Scripts\python.exe scripts\database_admin.py migrate --local-mysql --source-stopped
```

回退时先停 API 和 Worker，再把 `.env.local` 中的 `DATABASE_URL` 改为原 SQLite 的绝对连接地址，同时设置 `MYSQL_LOCAL_MANAGED=false`。请注意：原 SQLite 文件只包含切换前的数据，切换后在 MySQL 的新增修改不会自动回写 SQLite；有新增数据时应先进行反向迁移，不能直接切回旧快照。

默认测试强制使用独立临时 SQLite，不读取实际工程库。额外执行隔离 MySQL 集成测试：

```powershell
$env:RUN_MYSQL_TESTS = '1'
.\.venv\Scripts\python.exe -m pytest -q
```

这些测试只创建并清理随机命名的 `framecraft_test_*` 测试库，不删除应用库。当前 MySQL 为本机部署；多机、备份策略、服务器账户与跨版本 Schema 迁移另行规划。

## 模型服务配置说明

密钥通过安全配置流程写入后端未跟踪的 `.env.local` 或运行进程环境；不要发送到聊天、前端变量或版本控制。项目不附带密钥。

非秘密变量名和默认限制见 `.env.example`。后端支持：

- `OPENAI_BASE_URL` 或旧字段 `OPENAI_API_BASE`，基础地址需包含平台规定的 `/v1`；两个别名建议只配置一个，标准字段优先。
- `OPENAI_API_MODE=auto`：官方 `api.openai.com` 使用 Responses；自定义网关使用 Chat Completions。也可显式选择 `responses` 或 `chat_completions`。
- `TEACHER_MODEL`：兼容现有配置，作为 `OPENAI_TEXT_MODEL` 未配置时的回退。
- `OPENAI_VISION_MODEL`、`OPENAI_IMAGE_MODEL`：可单独覆盖视觉及图像模型。
- `OPENAI_TRANSCRIBE_MODEL`：仅在确有转写服务时配置；当前带时间戳实现支持 `whisper-1`。自定义网关不默认假设支持它。
- `OPENAI_IMAGE_SIZE`、`OPENAI_TIMEOUT_SECONDS`、`OPENAI_MAX_OUTPUT_TOKENS`：控制图像尺寸、请求超时、结构化输出上限。
- 中科大 Qwen flash/chat 默认使用已实测的非思考模式，减少结构化长输出的等待；reasoner 保留思考。可用 `OPENAI_ENABLE_THINKING=true/false` 显式覆盖，该参数仅发送给中科大 Qwen 路径。

配置读取顺序为 `.env copy.example`、`.env`、`.env.local`，同名字段后者覆盖前者，进程环境优先。支持文件中的 `export NAME=value` 写法。用户指定的 `.env copy.example` 实际含服务凭据，作为本地配置读取并已加入 `.gitignore`，不要把它当作可公开模板。密钥无需复制或写进前端。

当前中科大配置的实际映射：

| 职责 | 模型／协议 | 验证情况 |
|---|---|---|
| 文本与结构化创作 | `qwen3.8-flash-next` / Chat Completions | 真实调用通过 |
| 关键帧图像理解 | `qwen3.8-flash-next` / 图文消息 | 真实调用通过 |
| 新图生成 | `qwen-image-2.1` / Images API，1024×1024 | 真实调用通过 |
| 参考图编辑 | `qwen-image-2.1` / multipart 图片编辑 | 真实调用通过，已核对颜色编辑结果 |
| 带时间戳语音转写 | 未配置 | 使用 SRT，或仅提取采样帧可见字幕并提示遗漏风险 |

该映射仅对 `api.llm.ustc.edu.cn` 启用，显式配置的角色模型优先。其他自定义网关的模型需自行配置；不会把此密钥发送到 OpenAI 官方地址。

修改配置后重启 API 和 Worker；环境面板展示服务地址、协议、各角色模型、转写限制，并从 `/api/v1/models` 实际查询可用模型。配置存在不等于接口已经通过测试。

```powershell
.\.venv\Scripts\python.exe scripts\doctor.py
```

该诊断命令不访问 OpenAI、不输出密钥。

真实服务验收（会调用模型并可能产生费用；日志只输出安全元数据）：

```powershell
.\.venv\Scripts\python.exe scripts\check_provider.py
# 额外生成一张图片并执行一次参考图编辑
.\.venv\Scripts\python.exe scripts\check_provider.py --images
```

报告保存到 `data/diagnostics/provider-check.json`，测试图片也在该目录。

## 使用步骤

1. 创建工程，上传 30～180 秒原片，必要时上传 SRT；选择字幕表示用用户字幕替代转写，界面会注明未独立比对音频。
2. 点击开始拆解，等待 Worker。检查镜头、证据和角色；需要时修改镜头、资产，合并重复角色。
3. 确认原片分析，进入再创作，填写并保存创作要求。
4. 生成故事大纲，编辑后确认审核；生成制作方案，检查剧本、分镜时长和资产列表。
5. 在新剧资产库完善提示词；按需生成或上传图片。确认主角形象后，再通过参考图生成其他视角，人工审核一致性。
6. 到导出页核对待审核及缺图列表。可先导出草稿，完成审核后重新导出。

所有任务都需要 Worker；仅启动 FastAPI 时任务会停在等待状态。请求超时或 Worker 中断的外部调用可能已经计费，重试前阅读错误说明。重试只复用有效检查点，已变更输入需重新提交任务。

## 目录与接口

### 人物资产库与剧本解析

在工程内打开「资产库」，可按角色／场景／道具、原片／新剧和来源筛选，以卡片形式管理资产。人物编辑窗提供基本信息、完整人物设定、生成提示词、图片视图和历史版本；上传替换图和下载均按视图操作。

人物档案包含角色定位、身份、年龄、性格、目标、背景、关系、面容、发型、体态、服装、声音、表演和一致性要求等 15 个字段。「补全档案」结合现有文字和参考图整理设定，未知事实与创作建议分别标记，结果需人工确认。人物名称是剧中角色称谓，不识别演员真实身份。

「生成形象卡」分别调用图片 API 生成肖像、正面全身、侧面全身和背面全身，再由本地程序组合。四张原始视图均保留，可独立下载或替换；组合卡为居中排版，原始单图可查看完整画面。每个人物完整卡通常需要 4 次图片调用，重试复用有效检查点。服装、脸部一致性和身体补全仍需核对。

中科大接口默认以 4 秒的起始间隔串行调用图片模型；可在后端通过 `OPENAI_IMAGE_INTERVAL_SECONDS`（0～60 秒）调整。遇到接口限流，可稍后点击「从检查点重试」，已生成且校验成功的视图会复用。图片编辑的重试会重新打开参考文件，避免提交空文件流。

使用文字剧本进行二次创作：

1. 打开「剧本解析」，粘贴并保存单集剧本，或导入 TXT、MD、DOCX（2 MB 以内，正文 20～20,000 字）。
2. 点击「解析剧本」，得到人物档案、场景、道具、场次及逐字原文出处。剧本没有视频时间码，场次通过原文字符位置定位。
3. 进入资产库修订人物设定并生成形象；确认解析结果后点击「用于二次创作」。
4. 在「再创作」选择来源及「沿用已选资产」，勾选角色／场景／道具。生成的大纲与制作方案将沿用这些资产的编号、人物设定及图片，同时创作新事件和对白。也可选择重新设计。
5. 导出包包含人物档案 Markdown、资产 JSON、按 `sheet/portrait/front/side/back` 命名的图片、原始剧本及 `script_scenes.json`，可人工迁移到火山剧创。

文本保存、资产编辑、图片任务均校验输入版本。源剧本修改后，解析与下游创作会标为需更新；重复解析按人物名称和类别匹配稳定编号，避免因返回顺序变化串用人物图片。当前每个工程维护一份导入剧本，跨集人物统一管理留待扩展。

```text
backend/              API、Schema、数据库、媒体与模型服务、工作流
worker/               独立队列执行进程
frontend/src/         React 工作台、API 客户端、样式与前端测试
scripts/              安装、启动、诊断、OpenAPI 生成
tests/                使用隔离数据库的后端测试
data/                 本地数据库、上传、预览、参考图、生成图与导出（忽略提交）
```

当前工程内容使用通用 Entity / Revision 结构保存，`kind` 区分分析、创作要求、大纲、制作方案及资产，`scope` 区分原片与新剧。写入要求 `expected_version`，冲突返回 409；审核也创建版本。上游编辑将相关下游标记为需更新。合并保留原资产及历史，通过 `merged_into` 标识。

运行时契约见 `/docs`。生成静态契约和前端类型：

```powershell
.\.venv\Scripts\python.exe scripts\generate_openapi.py
npm.cmd --prefix frontend run generate:api
```

生成的 `src/api/generated.d.ts` 提供请求 Schema。界面聚合对象使用 `src/types.ts`；后端 Pydantic 执行模型结构与业务校验。数据库为首次启动建表；本 Demo 未引入跨版本自动迁移，修改数据结构前应备份 `data/`。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend worker scripts tests
npm.cmd --prefix frontend run lint
npm.cmd --prefix frontend run test
npm.cmd --prefix frontend run build
```

浏览器测试自动启动隔离 API（18401）与前端（5174），数据保存在 `.runtime/e2e-data`，不访问普通工程目录。首次使用需要安装测试浏览器：

```powershell
npm.cmd --prefix frontend exec -- playwright install chromium
npm.cmd --prefix frontend run test:e2e
```

若本机已有 Microsoft Edge，可免下载 Chromium：

```powershell
$env:PLAYWRIGHT_CHANNEL = 'msedge'
npm.cmd --prefix frontend run test:e2e
```

后端集成测试使用合成视频和测试替身验证整个流程，不产生 OpenAI 费用。浏览器测试在隔离目录创建 E2E 工程，验证导航、窄屏和表单，并用仅测试环境的拦截数据验证版本冲突后草稿保留，不冒充真实模型生成。真实视频上的角色识别准确率、生成质量、模型权限、实际费用仍需用真实账号和样片验证。

## 当前 Demo 的明确限制

- 默认视频最多 180 秒、200 MB；当前音频整体压缩转写，未实现长片音频分块和跨集人物跟踪。
- 镜头检测与视觉归并为待审核结果；不提供校准后的准确率，不自动认定说话人与角色的对应关系。
- 工作台具备镜头表单和资产表单；大纲／制作方案的完整结构通过 JSON 编辑器修改，尚未实现专业富文本编辑与拖拽剪辑。
- 同工程一次运行一个耗时任务；当前 MySQL 仍以单 Worker、本机工作台运行，不因更换数据库就自动具备多用户或分布式执行能力。
- 官方接口默认生图尺寸 1536×1024，自定义兼容接口默认 1024×1024，可配置覆盖。多视图一致性必须人工审核。
- 费用页显示服务端返回的 usage 与耗时，不提供未经校准的货币账单；缺失 usage 明确为未知。
- 图片与媒体不会自动删除；删除工程、存储清理、多用户登录和远程部署留待后续扩展。
- 通用资产包解析当前快照的分镜资产引用并写入版本号；火山剧创字段限制、导入模板与平台接口尚待真实验证。

## 设计与接口参考

- [项目落地方案](AI短剧再创作Agent_落地方案.md)
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [OpenAI 图像生成](https://developers.openai.com/api/docs/guides/image-generation)
- [OpenAI 语音转写](https://developers.openai.com/api/docs/guides/speech-to-text)
- [中科大平台 API 使用](https://llm.ustc.edu.cn/guide/api-usage/)
- [MySQL Community Server 下载](https://dev.mysql.com/downloads/mysql/8.4.html)
- [SQLAlchemy MySQL 方言与连接配置](https://docs.sqlalchemy.org/en/20/dialects/mysql.html)

本项目不需要复杂多代理框架。每个生成阶段都有明确输入、结构化输出、审核与版本边界，优先保证结果可回看、可修正、可交接。

### 页面登录保护

在 `.env.local` 中设置 `AUTH_USERNAME=admin` 和 `AUTH_PASSWORD=你自行设置的密码`，重启后端后使用该账号登录。密码仅由后端读取；未配置密码时禁止登录。现有模型服务凭据与页面登录密码相互独立。

未登录访问页面会跳转到 `/login`，登录成功回到原页面。所有 `/api/` 业务接口（含媒体、下载）都要求登录。会话使用 HttpOnly、SameSite=Strict Cookie，默认有效期 12 小时，可通过 `AUTH_SESSION_HOURS` 调整；退出或后端重启会使会话失效。通过 HTTPS 隧道部署时设置 `AUTH_COOKIE_SECURE=true`。当前为共享工作空间的单账号登录，运行单个后端进程，不包含用户注册和多用户数据隔离。
