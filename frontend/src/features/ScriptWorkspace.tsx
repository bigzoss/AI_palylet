import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Alert,
  Button,
  Empty,
  Form,
  Input,
  Space,
  Tabs,
  Tag,
  Upload,
} from "antd";
import { CloudUploadOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { api, post, taskBody } from "../api/client";
import { labels, type Entity, type ProjectDetail } from "../types";
import { useProjectAction } from "./useProjectAction";
import "./assets.css";

export default function ScriptWorkspace({
  project,
  busy,
}: {
  project: ProjectDetail;
  busy: boolean;
}) {
  const input = project.entities.find((e) => e.kind === "script_input");
  const script = project.entities.find((e) => e.kind === "script");
  return (
    <div className="script-workspace">
      <ScriptImport project={project} input={input} busy={busy} />
      <section className="panel script-results">
        <div className="panel-title">
          <span>剧本解析结果</span>
          {script && (
            <Tag color={script.status === "approved" ? "green" : "orange"}>
              {labels[script.status]} · V{script.version}
            </Tag>
          )}
        </div>
        {script ? (
          <ScriptResult project={project} script={script} busy={busy} />
        ) : (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="导入单集剧本，提取人物、场景、道具和场次"
          />
        )}
      </section>
    </div>
  );
}

function ScriptImport({
  project,
  input,
  busy,
}: {
  project: ProjectDetail;
  input?: Entity;
  busy: boolean;
}) {
  const [form] = Form.useForm();
  const action = useProjectAction(project.id);
  const [dirty, setDirty] = useState(false);
  const [version, setVersion] = useState(input?.version);
  const outdated = version !== input?.version;
  return (
    <section className="panel script-import">
      <div className="panel-title">
        <span>导入原始剧本</span>
        <Tag>单集 · 20～20,000 字</Tag>
      </div>
      <Alert
        type="info"
        showIcon
        message="提取人物设定与制作素材"
        description="支持粘贴文字或导入 TXT、MD、DOCX。原文未说明的信息标为未知；AI 提出的创作补全另行标记。"
      />
      {outdated && (
        <Alert
          className="spaced"
          type="warning"
          showIcon
          message="剧本已有新版本，当前草稿已保留"
          action={
            <Button
              onClick={() => {
                form.setFieldsValue(input?.content);
                setVersion(input?.version);
                setDirty(false);
              }}
            >
              载入最新剧本
            </Button>
          }
        />
      )}
      <Form
        form={form}
        layout="vertical"
        initialValues={input?.content || { title: project.name, text: "" }}
        onValuesChange={() => setDirty(true)}
        onFinish={(v) =>
          action.mutate(async () => {
            const saved = await post(`/projects/${project.id}/scripts`, {
              ...v,
              expected_version: version,
            });
            setVersion(saved.version);
            setDirty(false);
          })
        }
      >
        <Form.Item
          name="title"
          label="剧本 / 剧集名称"
          rules={[{ required: true }]}
        >
          <Input maxLength={100} />
        </Form.Item>
        <Form.Item
          name="text"
          label="剧本正文"
          rules={[
            { required: true },
            { min: 20, message: "请至少输入 20 字剧本内容" },
          ]}
        >
          <Input.TextArea
            rows={18}
            maxLength={20000}
            showCount
            placeholder={
              "第1场 便利店 夜 内\n人物：小林、店长\n动作：小林将一张旧照片放到柜台上。\n小林：这张照片上的人，你认识吗？"
            }
          />
        </Form.Item>
        <Space wrap>
          <Button
            type="primary"
            htmlType="submit"
            loading={action.isPending}
            disabled={busy}
          >
            保存剧本
          </Button>
          <Upload
            accept=".txt,.md,.docx"
            showUploadList={false}
            disabled={busy || dirty}
            beforeUpload={(file) => {
              action.mutate(async () => {
                const data = new FormData();
                data.append("file", file);
                const saved = await api(
                  `/projects/${project.id}/script-files${version ? "?expected_version=" + version : ""}`,
                  { method: "POST", body: data },
                );
                form.setFieldsValue(saved.content);
                setVersion(saved.version);
                setDirty(false);
              });
              return false;
            }}
          >
            <Button
              icon={<CloudUploadOutlined aria-hidden="true" />}
              disabled={busy || dirty}
            >
              导入文档
            </Button>
          </Upload>
          <Button
            icon={<ThunderboltOutlined aria-hidden="true" />}
            disabled={busy || dirty || outdated || !input}
            loading={action.isPending}
            onClick={() =>
              action.mutate(() =>
                post(
                  `/projects/${project.id}/script-parse-jobs`,
                  taskBody({
                    entity_id: input!.id,
                    expected_version: input!.version,
                  }),
                ),
              )
            }
          >
            解析剧本
          </Button>
        </Space>
        {dirty && <p className="muted">保存当前文字后，即可开始解析。</p>}
      </Form>
      <p className="muted">
        文档上限 2 MB。解析保留原文出处，不生成虚构的视频时间码。
      </p>
    </section>
  );
}

function ScriptResult({
  project,
  script,
  busy,
}: {
  project: ProjectDetail;
  script: Entity;
  busy: boolean;
}) {
  const action = useProjectAction(project.id);
  const content = script.content;
  const linked = new Set<string>(
    (content.scenes || []).flatMap((s: any) => [
      s.location_asset_id,
      ...s.character_ids,
      ...s.prop_ids,
    ]),
  );
  const assets = project.entities.filter(
    (e) =>
      e.kind === "asset" &&
      e.scope === "source" &&
      !e.content.retired &&
      !e.content.merged_into &&
      (e.content.origin_id === script.id || linked.has(e.content.id)),
  );
  const names = (ids: string[]) =>
    ids
      .map((id) => assets.find((a) => a.content.id === id)?.content.name || id)
      .join("、");
  return (
    <>
      <h2>{content.title}</h2>
      <p className="logline">{content.synopsis}</p>
      <div className="script-source-status">
        <Tag>
          {assets.filter((a) => a.content.type === "character").length} 位人物
        </Tag>
        <Tag>{content.scenes?.length || 0} 个场次</Tag>
        <Link to={`/projects/${project.id}/assets?scope=source`}>
          编辑人物与形象 →
        </Link>
      </div>
      <Tabs
        items={[
          {
            key: "scenes",
            label: "场次与资产",
            children: content.scenes?.map((s: any) => (
              <article className="script-scene" key={s.id}>
                <h3>{s.title}</h3>
                <small>
                  {names([s.location_asset_id].filter(Boolean))} ·{" "}
                  {names(s.character_ids)}
                </small>
                {s.prop_ids.length > 0 && (
                  <p>
                    <Tag>道具</Tag>
                    {names(s.prop_ids)}
                  </p>
                )}
                <p>{s.action}</p>
                {s.dialogue && (
                  <pre className="script-source-text">{s.dialogue}</pre>
                )}
                <details>
                  <summary>查看原文出处</summary>
                  <blockquote>{s.source_quote}</blockquote>
                  <small>
                    原文字符 {s.source_start}～{s.source_end}
                  </small>
                </details>
              </article>
            )),
          },
          {
            key: "patterns",
            label: "创作规律与待确认",
            children: (
              <>
                <ul>
                  {content.creative_patterns?.map((v: string, i: number) => (
                    <li key={i}>{v}</li>
                  ))}
                </ul>
                {content.uncertainties?.length > 0 && (
                  <Alert
                    showIcon
                    type="warning"
                    message="待人工确认"
                    description={content.uncertainties.join("；")}
                  />
                )}
              </>
            ),
          },
          {
            key: "original",
            label: "原始剧本",
            children: <pre className="script-source-text">{content.text}</pre>,
          },
        ]}
      />
      <Space wrap>
        <Button
          loading={action.isPending}
          disabled={
            busy ||
            script.status === "approved" ||
            script.status === "needs_update"
          }
          onClick={() =>
            action.mutate(() =>
              post(`/projects/${project.id}/reviews`, {
                entity_id: script.id,
                expected_version: script.version,
                status: "approved",
              }),
            )
          }
        >
          确认剧本解析
        </Button>
        <Link to={`/projects/${project.id}/adaptation?source=${script.id}`}>
          <Button type="primary" disabled={script.status !== "approved"}>
            用于二次创作
          </Button>
        </Link>
      </Space>
      {script.status === "needs_update" && (
        <p className="muted">原始剧本已修改，请重新解析后确认。</p>
      )}
    </>
  );
}
