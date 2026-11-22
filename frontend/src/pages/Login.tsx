import { useState } from "react";
import AuthLayout from "@/components/workspace/AuthLayout";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import api from "@/lib/api";
import { getApiErrorMessage } from "@/lib/errors";
import { useFeatures } from "@/lib/features";

export default function Login() {
  const features = useFeatures();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const formData = new FormData();
      formData.append("username", email);
      formData.append("password", password);

      const response = await api.post("/api/auth/login", formData);
      localStorage.setItem("token", response.data.access_token);
      localStorage.setItem("email", email.trim().toLowerCase());
      navigate("/dashboard");
    } catch (error: unknown) {
      const message = getApiErrorMessage(error, "登录失败，请检查邮箱和密码。");
      toast.error(/incorrect email or password/i.test(message) ? "邮箱或密码不正确。" : message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout>
      <form className="auth-card" onSubmit={handleLogin}>
        <div className="auth-card-header">
          <h2>登录</h2>
          <p>回到论文，继续上次的阅读。</p>
        </div>
        <div className="auth-fields">
          <div>
            <label className="ui-label" htmlFor="email">
              邮箱
            </label>
            <Input
              id="email"
              className="ui-input--lg"
              type="email"
              placeholder="name@example.com"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div>
            <label className="ui-label" htmlFor="password">
              密码
            </label>
            <Input
              id="password"
              className="ui-input--lg"
              autoComplete="current-password"
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
        </div>
        <Button size="lg" type="submit" disabled={loading}>
          {loading ? <Loader2 className="spin" /> : null}
          登录
          {!loading ? <ArrowRight /> : null}
        </Button>
        <p className="auth-footer">
          {features.registration ? (
            <>
              没有账户？<Link to="/register">注册</Link>
            </>
          ) : (
            "账号由管理员开通，请联系管理员。"
          )}
        </p>
      </form>
    </AuthLayout>
  );
}
