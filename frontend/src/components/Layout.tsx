import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Files, GraduationCap, LogOut, NotebookPen, Settings, UserRound } from "lucide-react";
import Brand from "@/components/Brand";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export default function Layout() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const email = localStorage.getItem("email") || "我的账户";
  const [dueCount, setDueCount] = useState<number | null>(null);
  useEffect(() => {
    if (pathname.startsWith("/reader/")) return;
    window.scrollTo(0, 0);
    let cancelled = false;
    void api
      .get<unknown[]>("/api/knowledge/flashcards/due?limit=100")
      .then(({ data }) => {
        if (!cancelled) setDueCount(data.length);
      })
      .catch(() => {
        if (!cancelled) setDueCount(null);
      });
    return () => {
      cancelled = true;
    };
  }, [pathname]);
  if (pathname.startsWith("/reader/"))
    return (
      <div className="reader-main">
        <Outlet />
      </div>
    );
  return (
    <div className="app-shell">
      <a className="skip-link" href="#workspace-content">
        跳到页面内容
      </a>
      <aside className="app-sidebar">
        <Link className="app-brand" to="/dashboard">
          <Brand />
        </Link>
        <nav className="app-navigation" aria-label="主要导航">
          <NavLink to="/dashboard">
            <Files size={19} />
            <span>我的论文</span>
          </NavLink>
          <Link
            to="/knowledge"
            className={pathname.startsWith("/knowledge") && pathname !== "/knowledge/review" ? "active" : ""}
            aria-current={pathname.startsWith("/knowledge") && pathname !== "/knowledge/review" ? "page" : undefined}
          >
            <NotebookPen size={19} />
            <span>知识笔记</span>
          </Link>
          <NavLink to="/knowledge/review">
            <GraduationCap size={19} />
            <span>复习</span>
            {dueCount !== null && dueCount > 0 && (
              <span className="app-due-count" aria-label={`${dueCount >= 100 ? "至少 100" : dueCount} 张到期卡片`}>
                {dueCount >= 100 ? "100+" : dueCount}
              </span>
            )}
          </NavLink>
        </nav>
        <div className="app-account">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="account-trigger" aria-label="打开账户菜单">
                <UserRound size={18} />
                <span>{email}</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-64">
              <DropdownMenuLabel className="break-all font-normal">{email}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => navigate("/settings")}>
                <Settings size={16} className="mr-2" />
                连接设置
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={() => {
                  localStorage.removeItem("token");
                  localStorage.removeItem("email");
                  navigate("/login");
                }}
              >
                <LogOut size={16} className="mr-2" />
                退出登录
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </aside>
      <main id="workspace-content" className="workspace-content">
        <Outlet />
      </main>
    </div>
  );
}
