import { useEffect, useState, type ReactNode } from "react";
import { Alert, Button, Form, Input, Spin } from "antd";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError, post } from "./api/client";

export function Auth({ children }: { children: ReactNode }) {
  const [state, setState] = useState<"loading" | "ready" | "guest" | "error">("loading");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const location = useLocation();
  const client = useQueryClient();
  const check = () => {
    setState("loading");
    api("/auth/me").then(() => setState("ready")).catch((e) => {
      setState(e instanceof ApiError && e.status === 401 ? "guest" : "error");
    });
  };
  useEffect(() => {
    check();
    const expired = () => {
      setState("guest");
      client.clear();
    };
    window.addEventListener("auth-expired", expired);
    return () => window.removeEventListener("auth-expired", expired);
  }, [client]);
  if (state === "loading") return <main className="login-shell"><Spin tip="正在验证登录状态" fullscreen /></main>;
  if (state === "error") return <main className="login-shell"><Alert type="error" message="无法验证登录状态，请检查后端连接" action={<Button onClick={check}>重试</Button>} /></main>;
  if (state === "ready") {
    if (location.pathname === "/login") {
      const target = new URLSearchParams(location.search).get("redirect") || "/projects";
      return <Navigate replace to={target.startsWith("/") && !target.startsWith("//") && !target.startsWith("/login") ? target : "/projects"} />;
    }
    return children;
  }
  if (location.pathname !== "/login") return <Navigate replace to={`/login?redirect=${encodeURIComponent(location.pathname + location.search + location.hash)}`} />;
  return <main className="login-shell">
    <section className="login-card" aria-labelledby="login-heading">
      <div className="login-brand">映作 · FRAMECRAFT</div>
      <h1 id="login-heading">登录创作空间</h1>
      <p>登录后继续管理工程、剧本与创作资产。</p>
      {error && <Alert type="error" showIcon message={error} role="alert" />}
      <Form layout="vertical" onFinish={async (values) => {
        setPending(true); setError("");
        try {
          await post("/auth/login", values);
          client.clear();
          setState("ready");
        } catch (e) { setError(e instanceof Error ? e.message : "登录失败，请重试"); }
        finally { setPending(false); }
      }}>
        <Form.Item name="username" label="用户名" rules={[{ required: true, message: "请输入用户名" }]}>
          <Input autoComplete="username" autoFocus maxLength={128} />
        </Form.Item>
        <Form.Item name="password" label="密码" rules={[{ required: true, message: "请输入密码" }]}>
          <Input.Password autoComplete="current-password" maxLength={1024} />
        </Form.Item>
        <Button type="primary" htmlType="submit" block loading={pending}>登录</Button>
      </Form>
    </section>
  </main>;
}

export function LogoutButton() {
  const client = useQueryClient();
  const navigate = useNavigate();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  return <span><Button loading={pending} onClick={async () => {
    setPending(true); setError("");
    try {
      await post("/auth/logout");
      client.clear();
      window.dispatchEvent(new Event("auth-expired"));
      navigate("/login", { replace: true });
    } catch { setError("退出失败，请重试"); }
    finally { setPending(false); }
  }}>退出登录</Button>{error && <span role="alert">{error}</span>}</span>;
}
