export interface Entity {
  id: string;
  project_id: string;
  kind: string;
  scope: "source" | "adaptation";
  version: number;
  status: string;
  content: Record<string, any>;
  updated_at: string;
}
export interface Media {
  id: string;
  kind: string;
  name: string;
  info: Record<string, any>;
}
export interface Job {
  id: string;
  kind: string;
  status: string;
  stage: string;
  progress: number;
  error?: string;
  error_code?: string;
  created_at: string;
  result?: Record<string, any>;
}
export interface Project {
  id: string;
  name: string;
  created_at: string;
}
export interface ProjectDetail extends Project {
  entities: Entity[];
  media: Media[];
  jobs: Job[];
}
export interface Shot {
  id: string;
  start_ms?: number;
  end_ms?: number;
  planned_duration_ms?: number;
  shot_size: string;
  camera: string;
  action: string;
  dialogue: string;
  sound?: string;
  asset_ids: string[];
  uncertainty?: string;
  frame_media_ids?: string[];
}
export const activeJob = (j: Job) =>
  ["queued", "running", "cancel_requested"].includes(j.status);
export function pollInterval(jobs?: Job[]) {
  return jobs?.some(activeJob) ? 2000 : false;
}
export const timecode = (ms = 0) =>
  `${String(Math.floor(ms / 60000)).padStart(2, "0")}:${((ms / 1000) % 60).toFixed(1).padStart(4, "0")}`;
export const labels: Record<string, string> = {
  pending: "待审核",
  approved: "已确认",
  rejected: "已退回",
  needs_update: "需更新",
  queued: "等待中",
  running: "处理中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
  cancel_requested: "取消中",
  character: "角色",
  scene: "场景",
  prop: "道具",
  analysis: "原片拆解",
  outline: "故事大纲",
  production: "剧本与分镜",
  image: "资产生图",
  export: "导出",
  brief: "创作要求",
  script: "剧本解析",
  script_parse: "剧本解析",
  profiles: "人物档案补全",
};
