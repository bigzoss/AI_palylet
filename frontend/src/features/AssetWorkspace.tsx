import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Checkbox,
  Empty,
  Form,
  Image,
  Input,
  Modal,
  Pagination,
  Select,
  Space,
  Tabs,
  Tag,
  Upload,
} from "antd";
import {
  CheckOutlined,
  CloudUploadOutlined,
  DownloadOutlined,
  EditOutlined,
  HistoryOutlined,
  PictureOutlined,
  PlusOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { api, BASE, mediaUrl, patch, post, taskBody } from "../api/client";
import { labels, type Entity, type ProjectDetail } from "../types";
import { useProjectAction } from "./useProjectAction";
import "./assets.css";

export const viewLabels: Record<string, string> = {
  sheet: "四视图形象卡",
  portrait: "人物肖像",
  front: "正面全身",
  side: "侧面全身",
  back: "背面全身",
};
export const profileLabels: Record<string, string> = {
  role_type: "角色定位",
  identity: "身份与职业",
  age: "年龄段",
  gender: "性别",
  personality: "性格特征",
  motivation: "目标与动机",
  backstory: "人物背景",
  relationships: "人物关系",
  appearance: "面容与外貌",
  hairstyle: "发型与发色",
  body: "体态与身形",
  clothing: "服装与配饰",
  voice: "声音特点",
  performance: "表演习惯",
  consistency: "形象一致性要求",
};
const profileKeys = Object.keys(profileLabels);
const meaningful = (value: unknown) =>
  typeof value === "string" &&
  !!value.trim() &&
  !/^(未知|待确认|unknown|待补充|无法确认)/i.test(value.trim());
function cover(entity: Entity) {
  return (
    entity.content.image_views?.sheet ||
    entity.content.image_views?.portrait ||
    entity.content.image_ids?.[0]
  );
}
function State({ entity }: { entity: Entity }) {
  return (
    <Tag
      color={
        entity.status === "approved"
          ? "green"
          : entity.status === "needs_update"
            ? "orange"
            : undefined
      }
    >
      {labels[entity.status]}
    </Tag>
  );
}

export default function AssetWorkspace({
  project,
  busy,
}: {
  project: ProjectDetail;
  busy: boolean;
}) {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const all = project.entities.filter(
    (e) => e.kind === "asset" && !e.content.merged_into && !e.content.retired,
  );
  const scope =
    params.get("scope") ||
    (all.some((e) => e.scope === "adaptation") ? "adaptation" : "source");
  const [type, setType] = useState("character");
  const [search, setSearch] = useState("");
  const [origin, setOrigin] = useState("all");
  const [selected, setSelected] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<string>();
  const [creating, setCreating] = useState(false);
  const [createForm] = Form.useForm();
  const action = useProjectAction(project.id);
  const assets = all.filter((e) => e.scope === scope);
  const shown = assets.filter(
    (e) =>
      e.content.type === type &&
      (e.content.name + e.content.description).includes(search) &&
      (origin === "all" || (e.content.origin_id || "video") === origin),
  );
  const targets = selected.length
    ? shown.filter((e) => selected.includes(e.id))
    : shown;
  const payload = (rows: Entity[], extra = {}) =>
    taskBody({
      asset_ids: rows.map((e) => e.id),
      expected_versions: Object.fromEntries(rows.map((e) => [e.id, e.version])),
      ...extra,
    });
  const hasSelection = targets.length > 0 && targets.length <= 20;
  const run = (endpoint: string, extra = {}) =>
    action.mutate(() =>
      post(`/projects/${project.id}/${endpoint}`, payload(targets, extra)),
    );
  const scripts = project.entities.filter((e) => e.kind === "script");
  return (
    <div className="library-workspace">
      {targets.length > 20 && (
        <Alert
          type="info"
          showIcon
          message="每批最多处理 20 项，请勾选需要处理的资产。"
        />
      )}
      <div className="library-titlebar">
        <div>
          <h2>创作资产库</h2>
          <p>人物设定与标准形象统一管理，随时用于下一次创作。</p>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined aria-hidden="true" />}
          onClick={() => setCreating(true)}
        >
          创建资产
        </Button>
      </div>
      <div className="asset-toolbar">
        <Tabs
          activeKey={scope}
          onChange={(s) => {
            setParams({ scope: s });
            setSelected([]);
            setPage(1);
          }}
          items={[
            { key: "source", label: "原片 / 剧本资产" },
            { key: "adaptation", label: "新剧创作资产" },
          ]}
        />
        <Input.Search
          aria-label="搜索资产"
          placeholder="搜索人物、场景或描述"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          allowClear
          style={{ maxWidth: 250 }}
        />
      </div>
      <div className="asset-subnav">
        {["character", "scene", "prop"].map((t) => (
          <button
            key={t}
            className={type === t ? "active" : ""}
            onClick={() => {
              setType(t);
              setPage(1);
              setSelected([]);
            }}
          >
            {labels[t]}资产{" "}
            <span>{assets.filter((e) => e.content.type === t).length}</span>
          </button>
        ))}
        <Select
          aria-label="资产来源筛选"
          value={origin}
          onChange={(v) => {
            setOrigin(v);
            setSelected([]);
            setPage(1);
          }}
          options={[
            { value: "all", label: "全部来源" },
            { value: "video", label: "原片提取 / 手动创建" },
            ...scripts.map((s) => ({ value: s.id, label: s.content.title })),
          ]}
          style={{ minWidth: 180, marginLeft: "auto" }}
        />
      </div>
      <div className="library-action-strip">
        <div>
          <span className="extract-mark">
            <PictureOutlined aria-hidden="true" />
          </span>
          <div>
            <strong>
              {type === "character" ? "完善人物创作资产" : "整理制作素材"}
            </strong>
            <small>
              {type === "character"
                ? "先完善人物设定，再生成“肖像 + 正侧背全身”的标准形象卡。"
                : "所有资产都可编辑、上传替换图、审核并导出。"}
            </small>
          </div>
        </div>
        <Space wrap>
          {type === "character" && (
            <Button
              icon={<ThunderboltOutlined aria-hidden="true" />}
              loading={action.isPending}
              disabled={busy || !hasSelection}
              onClick={() => run("asset-profile-jobs")}
            >
              补全档案（{targets.length}）
            </Button>
          )}
          <Button
            icon={<PictureOutlined aria-hidden="true" />}
            loading={action.isPending}
            disabled={busy || !hasSelection}
            onClick={() => run("asset-image-jobs", { image_view: "sheet" })}
          >
            {type === "character" ? "生成形象卡" : "生成资产图"}（
            {targets.length}）
          </Button>
        </Space>
      </div>
      <div className="library-selection">
        <Checkbox
          checked={
            !!shown.length && shown.every((e) => selected.includes(e.id))
          }
          indeterminate={
            selected.length > 0 && !shown.every((e) => selected.includes(e.id))
          }
          onChange={(e) =>
            setSelected(e.target.checked ? shown.map((x) => x.id) : [])
          }
        >
          全选
        </Checkbox>
        <span>
          共 {shown.length} 项 ·{" "}
          {selected.length
            ? `已选 ${selected.length} 项`
            : "未勾选时，批量操作处理当前筛选结果"}
        </span>
        <Button
          size="small"
          disabled={busy || !hasSelection}
          onClick={() =>
            action.mutate(async () => {
              await post(
                `/projects/${project.id}/reuse-assets`,
                payload(targets),
              );
              navigate(`/projects/${project.id}/assets?scope=adaptation`);
              setSelected([]);
            })
          }
        >
          复制到新剧资产库
        </Button>
        <Link to={`/projects/${project.id}/script`}>从剧本提取资产 →</Link>
      </div>
      {shown.length ? (
        <div className="library-card-grid">
          {shown.slice((page - 1) * 6, page * 6).map((asset) => {
            const count = profileKeys.filter(
              (k) =>
                meaningful(asset.content.profile?.[k]) &&
                !(asset.content.profile?.unknown_fields || []).includes(k),
            ).length;
            const image = cover(asset);
            return (
              <article
                className="asset-card library-asset-card"
                key={asset.id}
                onClick={() => setEditing(asset.id)}
              >
                <div
                  className="asset-checkbox"
                  onClick={(e) => e.stopPropagation()}
                >
                  <Checkbox
                    aria-label={`选择${asset.content.name}`}
                    checked={selected.includes(asset.id)}
                    onChange={(e) =>
                      setSelected((v) =>
                        e.target.checked
                          ? [...v, asset.id]
                          : v.filter((x) => x !== asset.id),
                      )
                    }
                  />
                </div>
                <button
                  className="library-card-open"
                  aria-label={`编辑${asset.content.name}`}
                  onClick={() => setEditing(asset.id)}
                >
                  <div className="library-card-picture">
                    {image ? (
                      <img
                        src={mediaUrl(image)}
                        alt={`${asset.content.name}形象图`}
                        loading="lazy"
                      />
                    ) : (
                      <div className="library-no-image">
                        <PictureOutlined aria-hidden="true" />
                        <small>等待生成标准形象</small>
                      </div>
                    )}
                    <span>
                      {asset.content.image_views?.sheet
                        ? "标准形象卡"
                        : image
                          ? "参考图片"
                          : "未生成图片"}
                    </span>
                  </div>
                  <div className="library-card-info">
                    <div>
                      <h3>{asset.content.name}</h3>
                      <State entity={asset} />
                    </div>
                    <small>
                      {asset.content.episode_name || project.name} · V
                      {asset.version}
                    </small>
                    <p>{asset.content.description || "尚未填写形象描述"}</p>
                    {type === "character" && (
                      <div className="profile-meter">
                        <span
                          style={{
                            width: `${(count / profileKeys.length) * 100}%`,
                          }}
                        />
                      </div>
                    )}
                    <div className="library-card-footer">
                      <span>
                        {type === "character"
                          ? `人物设定 ${count}/${profileKeys.length}`
                          : `${labels[type]}资产`}
                      </span>
                      <EditOutlined aria-hidden="true" />
                    </div>
                  </div>
                </button>
              </article>
            );
          })}
        </div>
      ) : (
        <section className="panel empty-assets">
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              scope === "source"
                ? "上传原片或导入剧本后，这里将出现提取的资产"
                : "完成再创作后，这里将出现新剧资产"
            }
          />
          <Link to={`/projects/${project.id}/script`}>
            <Button>导入剧本</Button>
          </Link>
        </section>
      )}
      <Pagination
        className="library-pagination"
        current={page}
        onChange={setPage}
        total={shown.length}
        pageSize={6}
        hideOnSinglePage
        showSizeChanger={false}
      />
      <p className="library-footnote">
        人物图为创作资产。原片参考、AI
        创作补全与人工设定分别记录，生成结果请审核后使用。
      </p>
      {editing && (
        <AssetDialog
          key={editing}
          entity={project.entities.find((e) => e.id === editing)!}
          project={project}
          busy={busy}
          onClose={() => setEditing(undefined)}
        />
      )}
      <Modal
        title="创建资产"
        open={creating}
        onCancel={() => setCreating(false)}
        okText="创建资产"
        confirmLoading={action.isPending}
        onOk={() =>
          createForm.validateFields().then((value) =>
            action.mutate(async () => {
              await post(`/projects/${project.id}/assets`, { ...value, scope });
              setCreating(false);
              createForm.resetFields();
            }),
          )
        }
      >
        <Form
          form={createForm}
          layout="vertical"
          initialValues={{
            type,
            name: "",
            description: "",
            episode_name: project.name,
          }}
        >
          <Form.Item name="name" label="资产名称" rules={[{ required: true }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="type" label="资产类型" rules={[{ required: true }]}>
            <Select
              options={["character", "scene", "prop"].map((v) => ({
                value: v,
                label: labels[v],
              }))}
            />
          </Form.Item>
          <Form.Item name="episode_name" label="所属剧集">
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="description" label="形象描述">
            <Input.TextArea rows={4} maxLength={4000} showCount />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

function AssetDialog({
  entity,
  project,
  busy,
  onClose,
}: {
  entity: Entity;
  project: ProjectDetail;
  busy: boolean;
  onClose: () => void;
}) {
  const [form] = Form.useForm();
  const [version, setVersion] = useState(entity.version);
  const [dirty, setDirty] = useState(false);
  const [view, setView] = useState("sheet");
  const [tab, setTab] = useState("basic");
  const [historyOpen, setHistoryOpen] = useState(false);
  const action = useProjectAction(project.id);
  const history = useQuery<any[]>({
    queryKey: ["asset-revisions", entity.id, entity.version],
    queryFn: () =>
      api(`/projects/${project.id}/entities/${entity.id}/revisions`),
    enabled: historyOpen,
  });
  const views = entity.content.image_views || {};
  const refs =
    entity.content.reference_image_ids ||
    entity.content.image_ids?.filter((id: string) =>
      project.media.some((m) => m.id === id && m.kind === "reference"),
    ) ||
    [];
  const imageId =
    view === "reference"
      ? refs[0]
      : views[view] ||
        (view === "sheet" ? entity.content.image_ids?.[0] : undefined);
  const outdated = version !== entity.version;
  const submit = async () => {
    const values = await form.validateFields();
    return action.mutateAsync(async () => {
      await patch(`/projects/${project.id}/assets/${entity.id}`, {
        expected_version: version,
        content: {
          ...entity.content,
          ...values,
          profile:
            entity.content.type === "character"
              ? { ...entity.content.profile, ...form.getFieldValue("profile") }
              : entity.content.profile,
        },
      });
      onClose();
    });
  };
  return (
    <Modal
      width={1120}
      style={{ top: 28 }}
      styles={{
        body: {
          maxHeight: "calc(100dvh - 180px)",
          overflowY: "auto",
          paddingRight: 4,
        },
      }}
      title={
        <span>
          资产信息 <State entity={entity} />
        </span>
      }
      open
      onCancel={onClose}
      footer={
        <div className="library-dialog-footer">
          <Space wrap>
            <Upload
              accept=".png,.jpg,.jpeg,.webp"
              disabled={dirty || outdated || view === "reference"}
              showUploadList={false}
              beforeUpload={(file) => {
                action.mutate(async () => {
                  const data = new FormData();
                  data.append("file", file);
                  await api(
                    `/projects/${project.id}/assets/${entity.id}/images?expected_version=${entity.version}&image_view=${view}`,
                    { method: "POST", body: data },
                  );
                });
                return false;
              }}
            >
              <Button
                icon={<CloudUploadOutlined aria-hidden="true" />}
                disabled={dirty || outdated || view === "reference"}
              >
                替换当前视图
              </Button>
            </Upload>
            {views[view] ? (
              <a
                href={`${BASE}/projects/${project.id}/assets/${entity.id}/images/${view}/download`}
              >
                <Button icon={<DownloadOutlined aria-hidden="true" />}>
                  下载图片
                </Button>
              </a>
            ) : imageId ? (
              <a href={mediaUrl(imageId)} target="_blank" rel="noreferrer">
                <Button>查看原图</Button>
              </a>
            ) : null}
            <Button
              icon={<HistoryOutlined aria-hidden="true" />}
              onClick={() => setHistoryOpen(!historyOpen)}
            >
              历史版本
            </Button>
          </Space>
          <Space wrap>
            <Button onClick={onClose}>取消</Button>
            <Button
              type="primary"
              loading={action.isPending}
              onClick={() => {
                void submit().catch(() => {});
              }}
            >
              保存新版本
            </Button>
          </Space>
        </div>
      }
    >
      {outdated && (
        <Alert
          className="spaced"
          showIcon
          type="info"
          message="资产已有新版本，当前编辑草稿仍被保留"
          action={
            <Button
              onClick={() => {
                form.setFieldsValue(entity.content);
                setVersion(entity.version);
                setDirty(false);
              }}
            >
              载入最新版本
            </Button>
          }
        />
      )}
      <div className="library-dialog-grid">
        <div className="library-image-column">
          <div className="library-large-preview">
            {imageId ? (
              <Image
                src={mediaUrl(imageId)}
                alt={`${entity.content.name} ${viewLabels[view] || "原片参考"}`}
              />
            ) : (
              <div className="library-no-image">
                <PictureOutlined aria-hidden="true" />
                <span>{viewLabels[view]}尚未生成</span>
              </div>
            )}
          </div>
          <div className="library-view-tabs">
            {Object.entries(viewLabels)
              .filter(
                ([key]) =>
                  entity.content.type === "character" || key === "sheet",
              )
              .map(([key, title]) => (
                <button
                  key={key}
                  className={view === key ? "active" : ""}
                  onClick={() => setView(key)}
                >
                  {title}
                  {views[key] && <CheckOutlined aria-hidden="true" />}
                </button>
              ))}
            {refs.length > 0 && (
              <button
                className={view === "reference" ? "active" : ""}
                onClick={() => setView("reference")}
              >
                原片参考
              </button>
            )}
          </div>
          <div className="library-image-note">
            <Tag>
              {views[view]
                ? "创作形象 · 待人工核对"
                : view === "reference" || imageId
                  ? "参考图片"
                  : "尚无图片"}
            </Tag>
            <span>
              组合卡含肖像及正侧背全身，单视图可分别生成或上传。参考中未出现的面部、身体和视角属于创作补全。
            </span>
          </div>
          <Button
            block
            icon={<ThunderboltOutlined aria-hidden="true" />}
            loading={action.isPending}
            disabled={busy || dirty || outdated || view === "reference"}
            onClick={() =>
              action.mutate(() =>
                post(
                  `/projects/${project.id}/assets/${entity.id}/image-jobs`,
                  taskBody({
                    expected_version: entity.version,
                    image_view: view,
                  }),
                ),
              )
            }
          >
            生成{viewLabels[view] || "形象图"}
          </Button>
          {dirty && <p className="muted">请先保存人物设定，再生成对应形象。</p>}
        </div>
        <div>
          <Form
            form={form}
            initialValues={{
              ...entity.content,
              profile: entity.content.profile || {},
            }}
            layout="vertical"
            onValuesChange={() => setDirty(true)}
          >
            <Tabs
              activeKey={tab}
              onChange={setTab}
              items={[
                {
                  key: "basic",
                  label: "基本信息",
                  children: (
                    <>
                      <Form.Item
                        name="name"
                        label="形象名称"
                        rules={[{ required: true }]}
                      >
                        <Input maxLength={100} />
                      </Form.Item>
                      <Form.Item label="形象类型">
                        <Input
                          value={`${labels[entity.content.type]}资产`}
                          disabled
                        />
                      </Form.Item>
                      <Form.Item name="episode_name" label="所属剧集">
                        <Input maxLength={100} placeholder={project.name} />
                      </Form.Item>
                      <Form.Item
                        name="description"
                        label="形象描述"
                        rules={[{ required: true }]}
                      >
                        <Input.TextArea rows={6} showCount maxLength={4000} />
                      </Form.Item>
                      <Form.Item
                        name="export_description"
                        label="工作台简介（可选）"
                      >
                        <Input.TextArea rows={3} showCount maxLength={200} />
                      </Form.Item>
                    </>
                  ),
                },
                ...(entity.content.type === "character"
                  ? [
                      {
                        key: "profile",
                        label: "完整人物设定",
                        children: (
                          <div className="library-profile-fields">
                            {Object.entries(profileLabels).map(
                              ([key, label]) => (
                                <Form.Item
                                  key={key}
                                  name={["profile", key]}
                                  label={label}
                                >
                                  <Input.TextArea
                                    autoSize={{ minRows: 1, maxRows: 4 }}
                                    placeholder="未确定的信息请写未知"
                                  />
                                </Form.Item>
                              ),
                            )}
                            <Form.Item
                              name={["profile", "inferred_fields"]}
                              label="创作补全字段"
                            >
                              <Select
                                mode="multiple"
                                options={profileKeys.map((k) => ({
                                  value: k,
                                  label: profileLabels[k],
                                }))}
                              />
                            </Form.Item>
                            <Form.Item
                              name={["profile", "unknown_fields"]}
                              label="待确认字段"
                            >
                              <Select
                                mode="multiple"
                                options={profileKeys.map((k) => ({
                                  value: k,
                                  label: profileLabels[k],
                                }))}
                              />
                            </Form.Item>
                          </div>
                        ),
                      },
                    ]
                  : []),
                {
                  key: "prompt",
                  label: "生成提示词",
                  children: (
                    <>
                      <Form.Item name="prompt" label="补充生成要求">
                        <Input.TextArea
                          rows={12}
                          placeholder="人物身份与服装、镜头风格、背景和光照……"
                        />
                      </Form.Item>
                      <Alert
                        type="info"
                        showIcon
                        message="系统会将人物档案、一致性要求与所选视图组合为最终提示词。"
                      />
                    </>
                  ),
                },
              ]}
            />
          </Form>
          <div className="library-review-row">
            <span>资产版本 V{entity.version}</span>
            <Button
              icon={<CheckOutlined aria-hidden="true" />}
              disabled={dirty || outdated || entity.status === "approved"}
              onClick={() =>
                action.mutate(() =>
                  post(`/projects/${project.id}/reviews`, {
                    entity_id: entity.id,
                    expected_version: entity.version,
                    status: "approved",
                  }),
                )
              }
            >
              确认审核
            </Button>
          </div>
        </div>
      </div>
      {entity.content.profile?.inferred_fields?.length > 0 && (
        <Alert
          className="spaced"
          type="warning"
          showIcon
          message="以下设定包含创作补全，需要确认"
          description={entity.content.profile.inferred_fields
            .map((k: string) => profileLabels[k] || k)
            .join("、")}
        />
      )}
      <AssetCorrections
        entity={entity}
        project={project}
        disabled={busy || dirty || outdated}
        onClose={onClose}
      />
      {historyOpen && (
        <div className="revision-list">
          <h4>历史版本</h4>
          {history.data?.map((r) => (
            <div key={r.id}>
              <b>V{r.version}</b> · {r.action}
              <p>{r.content.description}</p>
              {r.content.image_views?.sheet && (
                <img
                  width={150}
                  src={mediaUrl(r.content.image_views.sheet)}
                  alt={`V${r.version}形象卡`}
                />
              )}
            </div>
          ))}
        </div>
      )}
      {entity.content.evidence?.length > 0 && (
        <details className="evidence-details">
          <summary>原片证据（{entity.content.evidence.length}）</summary>
          {entity.content.evidence.map((e: any, i: number) => (
            <p key={i}>
              {e.shot_id} · {e.timestamp_ms}ms · {e.note}
            </p>
          ))}
        </details>
      )}
    </Modal>
  );
}

function AssetCorrections({
  entity,
  project,
  disabled,
  onClose,
}: {
  entity: Entity;
  project: ProjectDetail;
  disabled: boolean;
  onClose: () => void;
}) {
  const action = useProjectAction(project.id);
  const [target, setTarget] = useState<string>();
  const [name, setName] = useState("");
  const [shots, setShots] = useState<string[]>([]);
  const candidates = project.entities.filter(
    (e) =>
      e.kind === "asset" &&
      e.scope === entity.scope &&
      e.content.type === entity.content.type &&
      e.id !== entity.id &&
      !e.content.merged_into &&
      !e.content.retired,
  );
  const analysis = project.entities.find((e) => e.kind === "analysis");
  return (
    <>
      <details className="merge-details">
        <summary>合并重复资产</summary>
        <Space wrap>
          <Select
            aria-label="合并目标资产"
            placeholder="选择要保留的资产"
            value={target}
            onChange={setTarget}
            style={{ minWidth: 220 }}
            options={candidates.map((e) => ({
              value: e.id,
              label: e.content.name,
            }))}
          />
          <Button
            danger
            disabled={disabled || !target}
            loading={action.isPending}
            onClick={() =>
              action.mutate(async () => {
                await post(`/projects/${project.id}/asset-merges`, {
                  source_id: entity.id,
                  target_id: target,
                  source_version: entity.version,
                  target_version: candidates.find((e) => e.id === target)!
                    .version,
                });
                onClose();
              })
            }
          >
            合并并更新引用
          </Button>
        </Space>
      </details>
      {entity.scope === "source" &&
        entity.content.origin_kind !== "script" &&
        analysis && (
          <details className="merge-details">
            <summary>拆分误合并资产</summary>
            <Space wrap>
              <Input
                aria-label="拆分后的资产名称"
                placeholder="新资产名称"
                value={name}
                onChange={(e) => setName(e.target.value)}
                style={{ maxWidth: 220 }}
              />
              <Select
                mode="multiple"
                aria-label="拆分镜头"
                placeholder="选择迁移镜头"
                value={shots}
                onChange={setShots}
                style={{ minWidth: 220 }}
                options={(analysis.content.shots || [])
                  .filter((s: any) => s.asset_ids.includes(entity.content.id))
                  .map((s: any) => ({ value: s.id, label: s.id }))}
              />
              <Button
                disabled={disabled || !name.trim() || !shots.length}
                onClick={() =>
                  action.mutate(async () => {
                    await post(
                      `/projects/${project.id}/assets/${entity.id}/split`,
                      {
                        expected_version: entity.version,
                        name,
                        shot_ids: shots,
                      },
                    );
                    onClose();
                  })
                }
              >
                拆分并更新引用
              </Button>
            </Space>
          </details>
        )}
    </>
  );
}
