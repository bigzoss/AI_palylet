import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import App from "./App";
import { Auth } from "./Auth";
import "./styles.css";

const client = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 1000 },
    mutations: { retry: false },
  },
});
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#6754c7",
          borderRadius: 9,
          fontFamily: 'Inter, "Microsoft YaHei", sans-serif',
          colorText: "#252739",
          controlHeight: 40,
        },
        components: { Button: { primaryShadow: "none" } },
      }}
    >
      <AntApp>
        <QueryClientProvider client={client}>
          <BrowserRouter>
            <Auth><App /></Auth>
          </BrowserRouter>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
