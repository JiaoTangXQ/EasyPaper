import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import Login from "../Login";
import api from "@/lib/api";

// Mock sonner
vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

// Mock api
vi.mock("@/lib/api", () => ({
  default: {
    post: vi.fn(),
    get: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  },
}));

const renderLogin = () =>
  render(
    <MemoryRouter>
      <Login />
    </MemoryRouter>,
  );

describe("登录页", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockResolvedValue({ data: { registration: false, local_sync: false } });
  });
  it("渲染登录表单", () => {
    renderLogin();
    expect(screen.getByLabelText("邮箱")).toBeInTheDocument();
    expect(screen.getByLabelText("密码")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "登录" })).toBeInTheDocument();
  });

  it("服务器关闭注册时显示管理员开通提示", async () => {
    renderLogin();
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/api/auth/features"));
    expect(screen.queryByText("注册")).not.toBeInTheDocument();
    expect(screen.getByText("账号由管理员开通，请联系管理员。")).toBeInTheDocument();
  });

  it("允许注册时才显示注册入口", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { registration: true, local_sync: true } });
    renderLogin();
    expect(await screen.findByText("注册")).toBeInTheDocument();
  });

  it("配置加载失败也不开放注册", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("offline"));
    renderLogin();
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(screen.queryByText("注册")).not.toBeInTheDocument();
  });

  it("提交时禁用按钮", async () => {
    const { default: api } = await import("@/lib/api");
    (api.post as ReturnType<typeof vi.fn>).mockImplementation(
      () => new Promise(() => {}), // never resolves
    );

    renderLogin();
    const emailInput = screen.getByLabelText("邮箱");
    const passwordInput = screen.getByLabelText("密码");
    const button = screen.getByRole("button", { name: "登录" });

    fireEvent.change(emailInput, { target: { value: "test@test.com" } });
    fireEvent.change(passwordInput, { target: { value: "secret" } });
    fireEvent.submit(button);

    expect(button).toBeDisabled();
  });
});
