import { useRef, useState } from "react";
import {
  Link,
  NavLink,
  Route,
  Routes,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App as AntApp,
  Button,
  Checkbox,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Progress,
  Select,
  Spin,
  Tabs,
  Tag,
  Tooltip,
  Upload,
} from "antd";
import {
  ArrowLeftOutlined,
  ArrowRightOutlined,
  CheckOutlined,
  CloudUploadOutlined,
  DownloadOutlined,
  EditOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  HistoryOutlined,
  PictureOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  ScissorOutlined,
  SettingOutlined,
  StopOutlined,
  ThunderboltOutlined,
  VideoCameraOutlined,
} from "@ant-design/icons";
import { api, BASE, mediaUrl, patch, post, taskBody } from "./api/client";
import { LogoutButton } from "./Auth";
import AssetWorkspace from "./features/AssetWorkspace";
import ScriptWorkspace from "./features/ScriptWorkspace";
import {
  activeJob,
  labels,
  pollInterval,
  timecode,
  type Entity,
  type Project,
  type ProjectDetail,
  type Shot,
} from "./types";

const statusColor: Record<string, string> = {
  approved: "green",
  needs_update: "orange",
  rejected: "red",
  failed: "red",
  running: "purple",
  succeeded: "green",
};
const Status = ({ value }: { value: string }) => (
  <Tag color={statusColor[value]}>{labels[value] || value}</Tag>
);

function useAction(projectId?: string) {
  const queryClient = useQueryClient();
  const { message } = AntApp.useApp();
  return useMutation({
    mutationFn: (fn: () => Promise<any>) => fn(),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: projectId ? ["project", projectId] : ["projects"],
      });
    },
    onError: (error: Error) => message.error(error.message, 6),
  });
}

export default function App() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => api("/health"),
    refetchInterval: 30000,
  });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const providerModels = useQuery({
    queryKey: ["provider-models"],
    queryFn: () => api("/models"),
    enabled: settingsOpen && !!health.data?.api_key_configured,
    retry: false,
    staleTime: 60000,
  });
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link to="/projects" className="brand">
          <span className="brand-mark">
            <ScissorOutlined aria-hidden="true" />
          </span>
          <span>
            映作<small>FRAMECRAFT</small>
          </span>
        </Link>
        <div className="sidebar-section">创作空间</div>
        <NavLink to="/projects" className="sidebar-link">
          <FolderOpenOutlined aria-hidden="true" /> 我的工程
        </NavLink>
        <div className="sidebar-note">
          <div className="orbit">
            <VideoCameraOutlined aria-hidden="true" />
          </div>
          <strong>从好故事，到新故事</strong>
          <p>拆解创作规律，沉淀角色、场景与分镜，让灵感成为可用的资产。</p>
          <span>VIDEO → STORY → ASSETS</span>
        </div>
        <div className="sidebar-bottom">
          <button onClick={() => setSettingsOpen(true)}>
            <SettingOutlined aria-hidden="true" /> 连接与环境{" "}
            <span
              className={`dot ${health.data?.api_key_configured ? "ready" : ""}`}
            />
          </button>
          <small>LOCAL WORKSPACE · V0.1</small>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <LogoutButton />
          <span>
            短剧再创作工作台 <span className="beta">DEMO</span>
          </span>
          <button
            type="button"
            className="connection"
            aria-label="查看连接与环境"
            onClick={() => setSettingsOpen(true)}
          >
            <span className={`dot ${health.data ? "ready" : ""}`} />
            {health.data ? "本地服务已连接" : "正在连接后端"}
          </button>
        </header>
        {health.isError && (
          <Alert
            banner
            type="error"
            message="后端尚未连接，请启动 FastAPI 服务后重试。"
          />
        )}
        {health.data && !health.data.api_key_configured && (
          <div className="configuration-note">
            <SettingOutlined aria-hidden="true" /> 模型服务
            尚未配置，可创建工程和上传视频；AI 拆解与生成将在后端配置后启用。
            <button onClick={() => setSettingsOpen(true)}>
              查看环境 <ArrowRightOutlined aria-hidden="true" />
            </button>
          </div>
        )}
        <Routes>
          <Route path="/projects" element={<Projects />} />
          <Route path="/projects/:projectId/:page" element={<Workspace />} />
          <Route path="*" element={<Projects />} />
        </Routes>
      </div>
      <Modal
        title="连接与环境"
        open={settingsOpen}
        footer={null}
        onCancel={() => setSettingsOpen(false)}
      >
        <p>模型服务凭据由后端读取，此处仅展示服务信息与可用模型。</p>
        <div className="environment">
          <p>
            模型服务 <strong>{health.data?.provider?.name || "未连接"}</strong>
          </p>
          <p>
            API 地址 <code>{health.data?.provider?.base_url || "未知"}</code>
          </p>
          <p>
            调用协议 <code>{health.data?.provider?.protocol || "未知"}</code>
          </p>
          <p>
            后端服务 <Status value={health.data ? "succeeded" : "failed"} />
          </p>
          <p>
            媒体工具{" "}
            <Status value={health.data?.media_ready ? "succeeded" : "failed"} />
          </p>
          <p>
            API 密钥{" "}
            <Tag>
              {health.data?.api_key_configured ? "已配置（未展示）" : "未配置"}
            </Tag>
          </p>
          {Object.entries(health.data?.models || {}).map(([k, v]) => (
            <p key={k}>
              {k}
              <code>{String(v || "未配置")}</code>
            </p>
          ))}
        </div>
        {health.data?.api_key_configured &&
          !health.data?.capabilities?.transcription && (
            <Alert
              className="spaced"
              showIcon
              type="warning"
              message="语音转写尚未配置"
              description={health.data?.transcription_note}
            />
          )}
        {providerModels.data && (
          <div className="environment">
            <h4>当前凭据可用模型</h4>
            {providerModels.data.data.map((model: { id: string }) => (
              <Tag key={model.id}>{model.id}</Tag>
            ))}
          </div>
        )}
        {providerModels.isError && (
          <Alert
            className="spaced"
            type="warning"
            message="模型列表查询失败"
            description={providerModels.error.message}
          />
        )}
        <Alert
          type="info"
          showIcon
          message="已配置表示后端已读取配置，不代表所有接口均已验证。可用模型列表由实际服务返回，生成结果仍需人工审核。"
        />
      </Modal>
    </div>
  );
}

function Projects() {
  const projects = useQuery<Project[]>({
    queryKey: ["projects"],
    queryFn: () => api("/projects"),
  });
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const action = useAction();
  const navigate = useNavigate();
  const create = () =>
    action.mutate(async () => {
      const p = await post<Project>("/projects", { name });
      setCreateOpen(false);
      setName("");
      navigate(`/projects/${p.id}/analysis`);
    });
  return (
    <main className="page projects-page">
      <div className="eyebrow">YOUR CREATIVE WORKSPACE</div>
      <div className="page-heading">
        <div>
          <h1>
            我的工程<span className="count">{projects.data?.length || 0}</span>
          </h1>
          <p>从一段原片开始，构建属于你的新故事。</p>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined aria-hidden="true" />}
          onClick={() => setCreateOpen(true)}
        >
          新建工程
        </Button>
      </div>
      <section className="intro-panel">
        <div className="intro-copy">
          <Tag bordered={false}>VIDEO TO CREATION</Tag>
          <h2>
            看见故事背后的
            <br />
            创作逻辑。
          </h2>
          <p>
            提取原片的角色、镜头与叙事节奏，
            <br />
            再将它们转化为全新的创作资产。
          </p>
          <Button
            icon={<PlusOutlined aria-hidden="true" />}
            onClick={() => setCreateOpen(true)}
          >
            开始一个新故事 <ArrowRightOutlined aria-hidden="true" />
          </Button>
        </div>
        <div className="intro-visual" aria-hidden="true">
          <div className="film-line" />
          <div className="visual-frame f-one">
            <span>01 / ANALYZE</span>
            <VideoCameraOutlined aria-hidden="true" />
            <div className="frame-bars">
              <i />
              <i />
              <i />
            </div>
          </div>
          <div className="visual-frame f-two">
            <span>02 / RECREATE</span>
            <FileTextOutlined aria-hidden="true" />
            <div className="frame-bars">
              <i />
              <i />
              <i />
            </div>
          </div>
          <div className="visual-frame f-three">
            <span>03 / PRODUCE</span>
            <PictureOutlined aria-hidden="true" />
            <div className="frame-bars">
              <i />
              <i />
              <i />
            </div>
          </div>
        </div>
      </section>
      <div className="section-title">
        <h3>全部工程</h3>
        <span>本地保存 · 随时继续</span>
      </div>
      {projects.isPending ? (
        <Spin />
      ) : projects.isError ? (
        <Alert
          type="error"
          message="无法加载工程"
          action={<Button onClick={() => projects.refetch()}>重试</Button>}
        />
      ) : (
        <div className="project-grid">
          {projects.data?.map((p, i) => (
            <Link
              to={`/projects/${p.id}/analysis`}
              className="project-card"
              key={p.id}
            >
              <div className={`project-cover tone-${i % 3}`}>
                <VideoCameraOutlined aria-hidden="true" />
                <span>DRAMA PROJECT</span>
              </div>
              <div className="project-card-body">
                <h3>{p.name}</h3>
                <p>
                  {new Date(p.created_at).toLocaleDateString("zh-CN")} 创建{" "}
                  <ArrowRightOutlined aria-hidden="true" />
                </p>
              </div>
            </Link>
          ))}
          <button className="create-tile" onClick={() => setCreateOpen(true)}>
            <PlusOutlined aria-hidden="true" />
            <strong>新建短剧工程</strong>
            <span>上传原片，开始拆解</span>
          </button>
        </div>
      )}
      <div className="workflow-guide">
        {[
          ["01", "拆解原片", "镜头、对白与创作规律"],
          ["02", "设计新故事", "确认大纲，生成剧本与分镜"],
          ["03", "沉淀资产", "角色、场景、道具与创作包"],
        ].map(([n, title, desc]) => (
          <div key={n}>
            <b>{n}</b>
            <span>
              <strong>{title}</strong>
              <small>{desc}</small>
            </span>
          </div>
        ))}
      </div>
      <Modal
        title="新建短剧工程"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={create}
        confirmLoading={action.isPending}
        okText="创建工程"
        okButtonProps={{ disabled: !name.trim() }}
      >
        <Form layout="vertical">
          <Form.Item label="工程名称" htmlFor="project-name" required>
            <Input
              id="project-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onPressEnter={() => name.trim() && create()}
              maxLength={100}
              placeholder="例如：返乡之后 · 第一集"
              autoFocus
            />
          </Form.Item>
        </Form>
      </Modal>
    </main>
  );
}

function Workspace() {
  const { projectId = "", page = "analysis" } = useParams();
  const query = useQuery<ProjectDetail>({
    queryKey: ["project", projectId],
    queryFn: () => api(`/projects/${projectId}`),
    refetchInterval: (q) => pollInterval(q.state.data?.jobs),
  });
  const action = useAction(projectId);
  if (query.isPending)
    return (
      <div className="page">
        <Spin />
      </div>
    );
  if (query.isError || !query.data)
    return (
      <div className="page">
        <Alert type="error" message={query.error?.message || "工程不存在"} />
      </div>
    );
  const project = query.data;
  const running = project.jobs.find(activeJob);
  const nav = [
    ["analysis", "原片拆解", <VideoCameraOutlined aria-hidden="true" />],
    ["script", "剧本解析", <FileTextOutlined aria-hidden="true" />],
    ["adaptation", "再创作", <ThunderboltOutlined aria-hidden="true" />],
    ["assets", "资产库", <PictureOutlined aria-hidden="true" />],
    ["export", "导出创作包", <DownloadOutlined aria-hidden="true" />],
  ];
  return (
    <main className="page workspace-page">
      <Link className="back-link" to="/projects">
        <ArrowLeftOutlined aria-hidden="true" /> 全部工程
      </Link>
      <div className="page-heading">
        <div>
          <h1>{project.name}</h1>
          <p>拆解、重构，让每一份灵感都有迹可循。</p>
        </div>
        <Tag className="local-tag">本地工程</Tag>
      </div>
      <nav className="workspace-nav">
        {nav.map(([key, title, icon]) => (
          <NavLink key={String(key)} to={`/projects/${projectId}/${key}`}>
            {icon} {title}
          </NavLink>
        ))}
      </nav>
      {running && (
        <div className="job-progress">
          <div>
            <ThunderboltOutlined aria-hidden="true" />
            <strong>
              {labels[running.kind]} · {running.stage}
            </strong>
            <span>{running.progress}%</span>
            <Button
              size="small"
              icon={<StopOutlined aria-hidden="true" />}
              disabled={running.status === "cancel_requested"}
              onClick={() =>
                action.mutate(() => post(`/jobs/${running.id}/cancel`))
              }
            >
              取消任务
            </Button>
          </div>
          <Progress
            percent={running.progress}
            showInfo={false}
            strokeColor="#7460cf"
            size="small"
          />
        </div>
      )}
      {!running && project.jobs[0]?.status === "failed" && (
        <Alert
          className="spaced"
          showIcon
          type="error"
          message={`${labels[project.jobs[0].kind]}失败`}
          description={project.jobs[0].error}
          action={
            <Button
              loading={action.isPending}
              onClick={() =>
                action.mutate(() =>
                  post(`/jobs/${project.jobs[0].id}/retry`, taskBody()),
                )
              }
            >
              从检查点重试
            </Button>
          }
        />
      )}
      {page === "analysis" && <Analysis project={project} busy={!!running} />}
      {page === "adaptation" && (
        <Adaptation project={project} busy={!!running} />
      )}
      {page === "assets" && (
        <AssetWorkspace project={project} busy={!!running} />
      )}
      {page === "script" && (
        <ScriptWorkspace project={project} busy={!!running} />
      )}
      {page === "export" && <Exports project={project} busy={!!running} />}
    </main>
  );
}

function Review({ entity, projectId }: { entity: Entity; projectId: string }) {
  const action = useAction(projectId);
  return (
    <div className="review-control">
      <Status value={entity.status} />
      <Button
        icon={<CheckOutlined aria-hidden="true" />}
        disabled={entity.status === "approved"}
        loading={action.isPending}
        onClick={() =>
          action.mutate(() =>
            post(`/projects/${projectId}/reviews`, {
              entity_id: entity.id,
              expected_version: entity.version,
              status: "approved",
            }),
          )
        }
      >
        确认审核
      </Button>
      {entity.status === "approved" && (
        <Button
          type="text"
          onClick={() =>
            action.mutate(() =>
              post(`/projects/${projectId}/reviews`, {
                entity_id: entity.id,
                expected_version: entity.version,
                status: "pending",
              }),
            )
          }
        >
          撤回
        </Button>
      )}
    </div>
  );
}

function Analysis({
  project,
  busy,
}: {
  project: ProjectDetail;
  busy: boolean;
}) {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => api("/health"),
  });
  const analysis = project.entities.find((e) => e.kind === "analysis");
  const videos = project.media.filter((m) => m.kind === "video");
  const subtitles = project.media.filter((m) => m.kind === "subtitle");
  const [videoId, setVideoId] = useState<string>();
  const [subtitleId, setSubtitleId] = useState<string>();
  const [editing, setEditing] = useState<Shot>();
  const [params, setParams] = useSearchParams();
  const video = useRef<HTMLVideoElement>(null);
  const [playingMs, setPlayingMs] = useState(0);
  const [mobilePanel, setMobilePanel] = useState("shots");
  const selectedId = params.get("shot");
  const shots = (analysis?.content.shots || []) as Shot[];
  const selected = shots.find((s) => s.id === selectedId) || shots[0];
  const action = useAction(project.id);
  const sourceAssets = project.entities.filter(
    (e) => e.kind === "asset" && e.scope === "source" && !e.content.merged_into,
  );
  const upload = async (file: File) => {
    const data = new FormData();
    data.append("file", file);
    const result = await api(`/projects/${project.id}/media`, {
      method: "POST",
      body: data,
    });
    if (result.kind === "video") setVideoId(result.id);
    else setSubtitleId(result.id);
    return result;
  };
  const seek = (shot: Shot) => {
    setParams({ shot: shot.id }, { replace: true });
    setPlayingMs(shot.start_ms || 0);
    if (video.current && video.current.readyState >= 1)
      video.current.currentTime = (shot.start_ms || 0) / 1000;
  };
  return (
    <>
      {health.data?.api_key_configured &&
        !health.data?.capabilities?.transcription && (
          <Alert
            className="spaced"
            showIcon
            type="warning"
            message="建议同时上传 SRT 字幕"
            description={health.data?.transcription_note}
          />
        )}
      <div className="upload-toolbar">
        <div>
          <Select
            aria-label="选择原片"
            value={videoId || analysis?.content.media_id || videos.at(-1)?.id}
            placeholder="选择已上传原片"
            style={{ minWidth: 210 }}
            options={videos.map((m) => ({ value: m.id, label: m.name }))}
            onChange={setVideoId}
          />
          <Select
            aria-label="选择字幕"
            allowClear
            value={subtitleId}
            placeholder="可选：使用 SRT 字幕"
            options={subtitles.map((m) => ({ value: m.id, label: m.name }))}
            onChange={setSubtitleId}
            style={{ minWidth: 190 }}
          />
        </div>
        <div>
          <Upload
            accept=".mp4,.mov,.srt"
            showUploadList={false}
            beforeUpload={(file) => {
              action.mutate(() => upload(file));
              return false;
            }}
          >
            <Button
              icon={<CloudUploadOutlined aria-hidden="true" />}
              loading={action.isPending}
            >
              上传原片／字幕
            </Button>
          </Upload>
          <Button
            type="primary"
            icon={<ScissorOutlined aria-hidden="true" />}
            disabled={busy || !videos.length}
            loading={action.isPending}
            onClick={() =>
              action.mutate(() =>
                post(
                  `/projects/${project.id}/analysis-jobs`,
                  taskBody({
                    media_id:
                      videoId ||
                      analysis?.content.media_id ||
                      videos.at(-1)?.id,
                    subtitle_id: subtitleId,
                  }),
                ),
              )
            }
          >
            {analysis ? "重新拆解" : "开始拆解"}
          </Button>
        </div>
      </div>
      {!analysis ? (
        <section className="empty-workspace">
          <div className="empty-illustration">
            <VideoCameraOutlined aria-hidden="true" />
            <span className="scan-line" />
          </div>
          <h2>
            {videos.length
              ? "原片已就绪，开始拆解故事"
              : "让一段原片，成为创作的起点"}
          </h2>
          <p>上传 30～180 秒的短剧片段，提取镜头、对白、角色与叙事节奏。</p>
          <div className="empty-hints">
            <span>MP4 / MOV</span>
            <span>最大 200 MB</span>
            <span>可附 SRT 字幕</span>
          </div>
          {videos.length > 0 && (
            <video
              className="initial-preview"
              controls
              src={mediaUrl(videos.at(-1)!.id)}
            />
          )}
        </section>
      ) : (
        <>
          <div className="section-title">
            <h3>
              原片拆解 <span className="count">{shots.length} 镜头</span>
            </h3>
            <Review entity={analysis} projectId={project.id} />
          </div>
          <div className="mobile-switch">
            <Tabs
              activeKey={mobilePanel}
              onChange={setMobilePanel}
              items={[
                { key: "shots", label: "分镜" },
                { key: "assets", label: "资产" },
                { key: "video", label: "预览" },
              ]}
            />
          </div>
          <div className={`analysis-layout mobile-${mobilePanel}`}>
            <section className="panel asset-rail">
              <div className="panel-title">
                原片资产 <span>{sourceAssets.length}</span>
              </div>
              <div className="rail-list">
                {sourceAssets.length ? (
                  sourceAssets.map((a) => (
                    <div className="rail-asset" key={a.id}>
                      {a.content.image_ids?.[0] ? (
                        <img
                          loading="lazy"
                          src={mediaUrl(a.content.image_ids[0])}
                          alt={a.content.name}
                        />
                      ) : (
                        <div className="mini-placeholder">
                          <PictureOutlined aria-hidden="true" />
                        </div>
                      )}
                      <div>
                        <strong>{a.content.name}</strong>
                        <small>
                          {labels[a.content.type]} · {labels[a.status]}
                        </small>
                      </div>
                    </div>
                  ))
                ) : (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="尚无资产"
                  />
                )}
              </div>
              <Link
                className="rail-footer"
                to={`/projects/${project.id}/assets?scope=source`}
              >
                管理全部资产 <ArrowRightOutlined aria-hidden="true" />
              </Link>
            </section>
            <section className="panel shot-panel">
              <div className="panel-title">
                分镜脚本 <Tag bordered={false}>原片参考</Tag>
              </div>
              <div className="shot-list">
                {shots.map((s, i) => (
                  <article
                    key={s.id}
                    className={`shot-row ${selected?.id === s.id ? "selected" : ""} ${playingMs >= (s.start_ms || 0) && playingMs < (s.end_ms || 0) ? "playing" : ""}`}
                  >
                    <button
                      className="shot-select"
                      onClick={() => seek(s)}
                      aria-label={`定位镜头 ${i + 1}`}
                    >
                      <span className="shot-index">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      {s.frame_media_ids?.[0] && (
                        <img
                          src={mediaUrl(s.frame_media_ids[0])}
                          alt={`镜头 ${i + 1} 参考帧`}
                          loading="lazy"
                        />
                      )}
                      <div className="shot-copy">
                        <div>
                          <strong>
                            {s.shot_size || "待确认"} · {s.camera}
                          </strong>
                          <time>
                            {timecode(s.start_ms)} — {timecode(s.end_ms)}
                          </time>
                        </div>
                        <p>{s.action}</p>
                        {s.dialogue && <blockquote>{s.dialogue}</blockquote>}
                        {s.uncertainty && (
                          <small className="uncertainty">
                            待核对：{s.uncertainty}
                          </small>
                        )}
                      </div>
                    </button>
                    <Tooltip title="编辑镜头">
                      <Button
                        type="text"
                        aria-label={`编辑镜头 ${i + 1}`}
                        icon={<EditOutlined aria-hidden="true" />}
                        onClick={() => setEditing(s)}
                      />
                    </Tooltip>
                  </article>
                ))}
              </div>
            </section>
            <section className="panel preview-panel">
              <div className="panel-title">
                视频预览 <PlayCircleOutlined aria-hidden="true" />
              </div>
              <video
                ref={video}
                src={mediaUrl(analysis.content.preview_media_id)}
                controls
                onLoadedMetadata={() => {
                  if (video.current)
                    video.current.currentTime =
                      (selected?.start_ms || 0) / 1000;
                }}
                onTimeUpdate={() =>
                  setPlayingMs((video.current?.currentTime || 0) * 1000)
                }
              />
              <div className="preview-caption">
                <span>当前时间</span>
                <code>{timecode(playingMs)}</code>
              </div>
              <Alert
                type="info"
                message="原片参考画面"
                description="提取结果需人工审核。点击分镜或下方关键帧回看证据。"
              />
            </section>
          </div>
          <div className="timeline panel">
            <div className="panel-title">
              关键帧时间轴 <small>点击定位 · 候选镜头</small>
            </div>
            <div className="timeline-track">
              {shots.map((s, i) => (
                <button
                  className={selected?.id === s.id ? "selected" : ""}
                  key={s.id}
                  onClick={() => seek(s)}
                >
                  {s.frame_media_ids?.[0] ? (
                    <img
                      src={mediaUrl(s.frame_media_ids[0])}
                      alt={`镜头 ${i + 1}`}
                      loading="lazy"
                    />
                  ) : (
                    <PictureOutlined aria-hidden="true" />
                  )}
                  <span>
                    {String(i + 1).padStart(2, "0")}
                    <time>{timecode(s.start_ms)}</time>
                  </span>
                </button>
              ))}
            </div>
          </div>
          <section className="panel story-pattern">
            <div className="panel-title">故事结构与创作规律</div>
            <div className="pattern-grid">
              {[
                ["hook", "开场钩子"],
                ["conflict", "核心冲突"],
                ["reversal", "反转"],
                ["ending", "结尾悬念"],
              ].map(([key, title]) => (
                <div key={key}>
                  <small>{title}</small>
                  <p>{analysis.content.pattern?.[key] || "未知"}</p>
                </div>
              ))}
            </div>
            <p className="pattern-summary">
              {analysis.content.pattern?.synopsis}
            </p>
            <div>
              {analysis.content.pattern?.reusable_patterns?.map((x: string) => (
                <Tag key={x}>{x}</Tag>
              ))}
            </div>
            <small className="muted">{analysis.content.transcript?.note}</small>
          </section>
          {editing && (
            <ShotEditor
              projectId={project.id}
              entity={analysis}
              shot={editing}
              onClose={() => setEditing(undefined)}
            />
          )}
        </>
      )}
    </>
  );
}

function ShotEditor({
  projectId,
  entity,
  shot,
  onClose,
}: {
  projectId: string;
  entity: Entity;
  shot: Shot;
  onClose: () => void;
}) {
  const [form] = Form.useForm();
  const action = useAction(projectId);
  return (
    <Modal
      title={`编辑镜头 ${shot.id}`}
      open
      onCancel={onClose}
      okText="保存新版本"
      confirmLoading={action.isPending}
      onOk={() =>
        form.validateFields().then((values) =>
          action.mutate(async () => {
            await patch(`/projects/${projectId}/shots/${shot.id}`, {
              expected_version: entity.version,
              content: values,
            });
            onClose();
          }),
        )
      }
    >
      <Form form={form} initialValues={shot} layout="vertical">
        <div className="two-fields">
          <Form.Item
            label="开始时间（毫秒）"
            name="start_ms"
            rules={[{ required: true }]}
          >
            <InputNumber min={0} />
          </Form.Item>
          <Form.Item
            label="结束时间（毫秒）"
            name="end_ms"
            rules={[{ required: true }]}
          >
            <InputNumber min={1} />
          </Form.Item>
        </div>
        <Form.Item name="shot_size" label="景别">
          <Input />
        </Form.Item>
        <Form.Item name="camera" label="机位与运镜">
          <Input />
        </Form.Item>
        <Form.Item
          name="action"
          label="画面与动作"
          rules={[{ required: true }]}
        >
          <Input.TextArea rows={3} />
        </Form.Item>
        <Form.Item name="dialogue" label="对白">
          <Input.TextArea rows={3} />
        </Form.Item>
        <Form.Item name="uncertainty" label="待核对信息">
          <Input.TextArea />
        </Form.Item>
      </Form>
      <p className="muted">
        保存会重置审核状态，并标记依赖产物需要更新。版本冲突时保留当前草稿。
      </p>
    </Modal>
  );
}

const initialBrief = {
  genre: "都市职场",
  audience: "面向成年观众，写实、紧凑、有反转",
  retain: "开场钩子、情绪起伏、反转节奏",
  rewrite: "重构人物关系、核心事件、对白和结局",
  requirements: "",
  duration_seconds: 90,
  max_characters: 3,
  max_scenes: 2,
  visual_style: "当代中国都市，自然光，写实摄影，9:16",
};

function Adaptation({
  project,
  busy,
}: {
  project: ProjectDetail;
  busy: boolean;
}) {
  const [sourceParams, setSourceParams] = useSearchParams();
  const sources = project.entities.filter((e) =>
    ["analysis", "script"].includes(e.kind),
  );
  const brief = project.entities.find((e) => e.kind === "brief");
  const source =
    sources.find(
      (e) =>
        e.id ===
        (sourceParams.get("source") || brief?.content._source_entity_id),
    ) || sources[0];
  const reusable = project.entities.filter(
    (e) => e.kind === "asset" && !e.content.merged_into && !e.content.retired,
  );
  const outline = project.entities.find((e) => e.kind === "outline");
  const production = project.entities.find((e) => e.kind === "production");
  const [form] = Form.useForm();
  const [editor, setEditor] = useState<Entity>();
  const action = useAction(project.id);
  return (
    <div className="adaptation-layout">
      <section className="panel brief-panel">
        <div className="panel-title">
          <span>
            <ThunderboltOutlined aria-hidden="true" /> 再创作要求
          </span>
          {brief && <Status value={brief.status} />}
        </div>
        <Form
          form={form}
          initialValues={brief?.content || initialBrief}
          layout="vertical"
          onFinish={(value) =>
            action.mutate(() =>
              post(`/projects/${project.id}/adaptations`, {
                brief: value,
                source_entity_id: source?.id,
                expected_source_version: source?.version,
              }),
            )
          }
        >
          <Form.Item label="创作来源">
            <Select
              aria-label="创作来源"
              value={source?.id}
              onChange={(id) => setSourceParams({ source: id })}
              placeholder="请先解析原片或剧本"
              options={sources.map((e) => ({
                value: e.id,
                label: `${e.kind === "script" ? "剧本" : "原片"} · ${e.content.title || project.name} · ${labels[e.status]}`,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="asset_strategy"
            label="人物与形象策略"
            initialValue="redesign"
          >
            <Select
              options={[
                { value: "redesign", label: "重新设计人物与形象" },
                { value: "reuse", label: "沿用已选资产，创作新的故事" },
              ]}
            />
          </Form.Item>
          <Form.Item
            noStyle
            shouldUpdate={(a, b) => a.asset_strategy !== b.asset_strategy}
          >
            {({ getFieldValue }) =>
              getFieldValue("asset_strategy") === "reuse" ? (
                <Form.Item
                  name="reuse_asset_ids"
                  label="沿用的角色、场景与道具"
                  rules={[{ required: true, message: "请选择需要沿用的资产" }]}
                >
                  <Select
                    mode="multiple"
                    optionFilterProp="label"
                    options={reusable.map((e) => ({
                      value: e.id,
                      label: `${e.content.name} · ${e.scope === "source" ? "来源资产" : "新剧资产"} · V${e.version}`,
                    }))}
                  />
                </Form.Item>
              ) : null
            }
          </Form.Item>
          <Form.Item label="故事题材" name="genre" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item label="观众与风格" name="audience">
            <Input />
          </Form.Item>
          <Form.Item label="保留的创作规律" name="retain">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item label="需要重新设计" name="rewrite">
            <Input.TextArea rows={2} />
          </Form.Item>
          <div className="three-fields">
            <Form.Item label="时长 / 秒" name="duration_seconds">
              <InputNumber min={30} max={180} />
            </Form.Item>
            <Form.Item label="最多角色" name="max_characters">
              <InputNumber min={1} max={6} />
            </Form.Item>
            <Form.Item label="最多场景" name="max_scenes">
              <InputNumber min={1} max={5} />
            </Form.Item>
          </div>
          <Form.Item label="视觉方向" name="visual_style">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item label="其他创作要求" name="requirements">
            <Input.TextArea
              rows={3}
              placeholder="新故事背景、人物目标、希望出现的冲突……"
            />
          </Form.Item>
          <Button
            block
            type="primary"
            htmlType="submit"
            loading={action.isPending}
            disabled={busy || source?.status !== "approved"}
          >
            保存并确认创作要求
          </Button>
          {source?.status !== "approved" && (
            <p className="muted">请先确认作为创作来源的原片或剧本解析。</p>
          )}
        </Form>
      </section>
      <div className="adaptation-results">
        <section className="panel">
          <div className="panel-title">
            <span>01 / 故事大纲</span>
            <Button
              icon={<ThunderboltOutlined aria-hidden="true" />}
              disabled={busy || brief?.status !== "approved"}
              onClick={() =>
                action.mutate(() =>
                  post(`/adaptations/${brief!.id}/outline-jobs`, taskBody()),
                )
              }
            >
              {outline ? "重新生成" : "生成大纲"}
            </Button>
          </div>
          {outline ? (
            <div className="document-body">
              <h2>{outline.content.title}</h2>
              <p className="logline">{outline.content.logline}</p>
              <ol className="beats">
                {outline.content.beats?.map((b: string, i: number) => (
                  <li key={i}>{b}</li>
                ))}
              </ol>
              <h4>结局</h4>
              <p>{outline.content.ending}</p>
              <h4>与原片的变化</h4>
              <ul>
                {outline.content.changes_from_source?.map(
                  (b: string, i: number) => (
                    <li key={i}>{b}</li>
                  ),
                )}
              </ul>
              <div className="document-actions">
                <Button
                  icon={<EditOutlined aria-hidden="true" />}
                  onClick={() => setEditor(outline)}
                >
                  编辑大纲
                </Button>
                <Review entity={outline} projectId={project.id} />
              </div>
            </div>
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="保存创作要求后，生成新故事大纲"
            />
          )}
        </section>
        <section className="panel">
          <div className="panel-title">
            <span>02 / 剧本、分镜与资产规划</span>
            <Button
              disabled={
                busy ||
                outline?.status !== "approved" ||
                brief?.status !== "approved"
              }
              icon={<ThunderboltOutlined aria-hidden="true" />}
              onClick={() =>
                action.mutate(() =>
                  post(`/adaptations/${brief!.id}/production-jobs`, taskBody()),
                )
              }
            >
              {production ? "重新生成" : "生成制作方案"}
            </Button>
          </div>
          {production ? (
            <div className="document-body">
              <Tabs
                items={[
                  {
                    key: "script",
                    label: "剧本",
                    children: (
                      <pre className="script-text">
                        {production.content.script}
                      </pre>
                    ),
                  },
                  {
                    key: "shots",
                    label: `分镜 ${production.content.shots?.length || 0}`,
                    children: (
                      <div>
                        {production.content.shots?.map((s: Shot) => (
                          <div className="new-shot" key={s.id}>
                            <div>
                              <Tag>{s.id}</Tag>
                              <small>
                                {(s.planned_duration_ms || 0) / 1000}s ·{" "}
                                {s.shot_size}
                              </small>
                            </div>
                            <p>{s.action}</p>
                            <blockquote>{s.dialogue}</blockquote>
                            <small>
                              {s.sound} · {s.camera}
                            </small>
                          </div>
                        ))}
                      </div>
                    ),
                  },
                  {
                    key: "quality",
                    label: "制作提示",
                    children: (
                      <ul>
                        {production.content.quality_notes?.map((x: string) => (
                          <li key={x}>{x}</li>
                        ))}
                      </ul>
                    ),
                  },
                ]}
              />
              <div className="document-actions">
                <Button
                  onClick={() => setEditor(production)}
                  icon={<EditOutlined aria-hidden="true" />}
                >
                  编辑制作方案
                </Button>
                <Review entity={production} projectId={project.id} />
              </div>
              <Link
                className="text-link"
                to={`/projects/${project.id}/assets?scope=adaptation`}
              >
                进入新剧资产库 <ArrowRightOutlined aria-hidden="true" />
              </Link>
            </div>
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="确认大纲后生成剧本、分镜与资产档案"
            />
          )}
        </section>
      </div>
      {editor && (
        <JsonEditor
          entity={editor}
          projectId={project.id}
          onClose={() => setEditor(undefined)}
        />
      )}
    </div>
  );
}

function JsonEditor({
  entity,
  projectId,
  onClose,
}: {
  entity: Entity;
  projectId: string;
  onClose: () => void;
}) {
  const [text, setText] = useState(JSON.stringify(entity.content, null, 2));
  const [error, setError] = useState("");
  const action = useAction(projectId);
  return (
    <Modal
      width={850}
      title={`编辑${labels[entity.kind]} · V${entity.version}`}
      open
      onCancel={onClose}
      confirmLoading={action.isPending}
      okText="保存新版本"
      onOk={() => {
        let content;
        try {
          content = JSON.parse(text);
          setError("");
        } catch {
          setError("JSON 格式无效，请检查引号和逗号");
          return;
        }
        action.mutate(async () => {
          await patch(`/projects/${projectId}/entities/${entity.id}`, {
            expected_version: entity.version,
            content,
          });
          onClose();
        });
      }}
    >
      <Alert
        type="info"
        message="结构化编辑：保留字段名与 ID，修改内容。保存会重新进入审核；后台刷新不会覆盖此草稿。"
      />
      <Input.TextArea
        aria-label="结构化文档内容"
        className="json-editor"
        rows={22}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      {error && <Alert type="error" message={error} />}
    </Modal>
  );
}

function Exports({ project, busy }: { project: ProjectDetail; busy: boolean }) {
  const [reference, setReference] = useState(false);
  const [showRuns, setShowRuns] = useState(false);
  const action = useAction(project.id);
  const unresolved = project.entities.filter(
    (e) => e.status !== "approved" && !e.content.merged_into,
  );
  const jobs = project.jobs.filter((j) => j.kind === "export");
  const runs = useQuery<any[]>({
    queryKey: ["runs", project.id],
    queryFn: () => api(`/projects/${project.id}/runs`),
    enabled: showRuns,
  });
  return (
    <div className="export-layout">
      <section className="panel export-main">
        <div className="export-icon">
          <DownloadOutlined aria-hidden="true" />
        </div>
        <div className="eyebrow">READY FOR PRODUCTION</div>
        <h2>把故事，交给下一步创作。</h2>
        <p>
          冻结当前版本，将剧本、分镜、提示词与图片
          <br />
          整理成可追溯的通用创作包。
        </p>
        <div className="export-formats">
          {["Markdown", "CSV", "JSON", "图片", "ZIP"].map((x) => (
            <Tag key={x}>{x}</Tag>
          ))}
        </div>
        <Alert
          showIcon
          type="info"
          message="火山剧创 · 人工迁移"
          description="当前导出为通用包。平台模板和接口尚未验证，不代表可直接批量导入。"
        />
        <Checkbox
          checked={reference}
          onChange={(e) => setReference(e.target.checked)}
        >
          包含原片参考截图（与新剧资产分开）
        </Checkbox>
        <Button
          size="large"
          type="primary"
          icon={<DownloadOutlined aria-hidden="true" />}
          loading={action.isPending}
          disabled={busy || !project.entities.length}
          onClick={() =>
            action.mutate(() =>
              post(
                `/projects/${project.id}/exports`,
                taskBody({ include_reference: reference }),
              ),
            )
          }
        >
          生成当前版本创作包
        </Button>
        <small className="muted">
          未审核或缺失内容会在 manifest 中标记为草稿。
        </small>
      </section>
      <div>
        <section className="panel">
          <div className="panel-title">
            审核与完整性 <span>{unresolved.length} 项待处理</span>
          </div>
          <div className="review-list">
            {unresolved.length ? (
              unresolved.map((e) => (
                <div key={e.id}>
                  <span>
                    {e.content.name || e.content.title || labels[e.kind]}
                  </span>
                  <Status value={e.status} />
                </div>
              ))
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  project.entities.length
                    ? "当前文档均已确认，请核对图片完整性"
                    : "暂无产物"
                }
              />
            )}
            {project.entities
              .filter(
                (e) =>
                  e.kind === "asset" &&
                  e.scope === "adaptation" &&
                  !e.content.image_ids?.length &&
                  !e.content.merged_into,
              )
              .map((e) => (
                <div key={`img-${e.id}`}>
                  <span>{e.content.name}</span>
                  <Tag color="orange">缺少图片</Tag>
                </div>
              ))}
          </div>
        </section>
        <section className="panel">
          <div className="panel-title">导出记录</div>
          {jobs.length ? (
            <div className="export-history">
              {jobs.map((j) => (
                <div key={j.id}>
                  <div>
                    <strong>
                      {new Date(j.created_at).toLocaleString("zh-CN")}
                    </strong>
                    <Status value={j.status} />
                  </div>
                  {j.status === "succeeded" && (
                    <a href={`${BASE}/exports/${j.id}/download`}>
                      <Button icon={<DownloadOutlined aria-hidden="true" />}>
                        {j.result?.manifest?.draft
                          ? "下载草稿 ZIP"
                          : "下载创作包"}
                      </Button>
                    </a>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="尚无导出记录"
            />
          )}
        </section>
        <Button
          type="text"
          icon={<HistoryOutlined aria-hidden="true" />}
          onClick={() => setShowRuns(!showRuns)}
        >
          查看处理记录与用量
        </Button>
        {showRuns && (
          <section className="panel run-list">
            {runs.data?.length ? (
              runs.data.map((r) => (
                <div key={r.id}>
                  <strong>{r.stage}</strong>
                  <Status value={r.status} />
                  <small>
                    {r.model || "本地处理"} ·{" "}
                    {r.elapsed_ms
                      ? `${(r.elapsed_ms / 1000).toFixed(1)}s`
                      : "耗时未知"}
                  </small>
                  <code>
                    {r.usage
                      ? JSON.stringify(r.usage)
                      : "usage 未提供，费用未知"}
                  </code>
                </div>
              ))
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="暂无调用记录"
              />
            )}
          </section>
        )}
      </div>
    </div>
  );
}
