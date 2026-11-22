import { useState } from "react";
import AuthLayout from "@/components/workspace/AuthLayout";
import { Link, useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import api from "@/lib/api";
import { getApiErrorMessage } from "@/lib/errors";
import { useFeatures } from "@/lib/features";

export default function Register() {
  const features = useFeatures();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await api.post("/api/auth/register", { email, password });
      toast.success("注册成功，请登录。");
      navigate("/login");
    } catch (error: unknown) {
      toast.error(getApiErrorMessage(error, "注册失败，请重试。"));
    } finally {
      setLoading(false);
    }
  };

  if (features.loaded && !features.registration)
    return (
      <AuthLayout>
        <div className="auth-card">
          <div className="auth-card-header">
            <h2>账号由管理员开通</h2>
            <p>此站点不开放自助注册。请联系管理员为你创建账号。</p>
          </div>
          <Button asChild variant="secondary" size="lg">
            <Link to="/login">返回登录</Link>
          </Button>
        </div>
      </AuthLayout>
    );

  return (
    <AuthLayout>
      <form className="auth-card" onSubmit={handleRegister}>
        <div className="auth-card-header">
          <h2>创建账户</h2>
          <p>保存论文、阅读位置和你的笔记。</p>
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
              autoComplete="new-password"
              minLength={12}
              type="password"
              required
              placeholder="至少 12 位"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
        </div>
        <Button size="lg" type="submit" disabled={loading || !features.loaded}>
          {loading && <Loader2 className="spin" />}
          创建账户
        </Button>
        <p className="auth-footer">
          已有账户？<Link to="/login">登录</Link>
        </p>
      </form>
    </AuthLayout>
  );
}
