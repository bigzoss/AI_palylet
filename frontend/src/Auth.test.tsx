import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Auth } from "./Auth";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function mount() {
  return render(<QueryClientProvider client={new QueryClient()}>
    <MemoryRouter initialEntries={["/projects/private/story?tab=1"]}>
      <Auth><div>受保护工程</div></Auth>
    </MemoryRouter>
  </QueryClientProvider>);
}

it("does not mount protected content while checking the session", () => {
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
  mount();
  expect(screen.queryByText("受保护工程")).toBeNull();
});

it("shows protected content after server verification", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ username: "admin" }) }));
  mount();
  expect(await screen.findByText("受保护工程")).toBeInTheDocument();
});

it("removes protected content when the session expires", async () => {
  vi.stubGlobal("matchMedia", () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }));
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ username: "admin" }) }));
  mount();
  await screen.findByText("受保护工程");
  act(() => { window.dispatchEvent(new Event("auth-expired")); });
  expect(screen.queryByText("受保护工程")).toBeNull();
  expect(await screen.findByRole("heading", { name: "登录创作空间" })).toBeInTheDocument();
});
