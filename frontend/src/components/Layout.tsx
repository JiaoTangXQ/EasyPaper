import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useCallback, useEffect, useState } from "react";
import { GraduationCap, Library, LogOut, NotebookPen, Search, Settings } from "lucide-react";
import api from "@/lib/api";
import Brand from "@/components/Brand";
import CommandPalette from "@/components/CommandPalette";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { currentEmail, logout, REVIEW_CHANGED } from "@/lib/session";

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

function useReviewDue(pathname: string) {
  const [due, setDue] = useState<number | null>(null);
  const load = useCallback(() => {
    let cancelled = false;
    void Promise.all([
      api.get<unknown[]>("/api/knowledge/flashcards/due?limit=100"),
      api.get<unknown[]>("/api/terms?due_only=true&limit=100"),
    ])
      .then(([cards, terms]) => {
        if (!cancelled) setDue(cards.data.length + terms.data.length);
      })
      .catch(() => {
        if (!cancelled) setDue(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  // Refresh when entering a workspace page and whenever a review is recorded.
  useEffect(() => {
    if (pathname.startsWith("/reader/")) return;
    return load();
  }, [pathname, load]);
  useEffect(() => {
    const refresh = () => void load();
    window.addEventListener(REVIEW_CHANGED, refresh);
    return () => window.removeEventListener(REVIEW_CHANGED, refresh);
  }, [load]);
  return due;
}

const links = [
  { to: "/dashboard", label: "我的论文", icon: Library, match: (path: string) => path.startsWith("/dashboard") },
  {
    to: "/knowledge",
    label: "知识笔记",
    icon: NotebookPen,
    match: (path: string) => path.startsWith("/knowledge") || path.startsWith("/terms"),
  },
  { to: "/review", label: "复习", icon: GraduationCap, match: (path: string) => path.startsWith("/review") },
];

export default function Layout() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const email = currentEmail();
  const [online, setOnline] = useState(() => navigator.onLine);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const due = useReviewDue(pathname);

  useEffect(() => {
    const handleOnline = () => setOnline(true);
    const handleOffline = () => setOnline(false);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!pathname.startsWith("/reader/")) window.scrollTo(0, 0);
  }, [pathname]);

  const networkStatus = !online ? (
    <div className="network-status" role="status" aria-live="polite">
      <span className="status-dot" />
      离线中 · 已保存的内容仍可查看，联网后自动同步
    </div>
  ) : null;
  const palette = <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />;

  if (pathname.startsWith("/reader/"))
    return (
      <div className="reader-main">
        {networkStatus}
        <Outlet />
        {palette}
      </div>
    );

  const badge = due !== null && due > 0 ? (due >= 200 ? "99+" : String(due)) : null;
  return (
    <div className="app-shell">
      {networkStatus}
      <a className="skip-link" href="#workspace-content">
        跳到页面内容
      </a>
      <header className="app-nav">
        <div className="app-nav-inner">
          <Link className="app-brand" to="/dashboard" aria-label="EasyPaper 首页">
            <Brand markSize={26} />
          </Link>
          <nav className="app-nav-links" aria-label="主要导航">
            {links.map(({ to, label, match }) => (
              <NavLink
                key={to}
                to={to}
                className={() => (match(pathname) ? "active" : "")}
                aria-current={match(pathname) ? "page" : undefined}
              >
                {label}
                {to === "/review" && badge ? (
                  <span className="count-badge" aria-label={`${badge} 项待复习`}>
                    {badge}
                  </span>
                ) : null}
              </NavLink>
            ))}
          </nav>
          <div className="app-nav-actions">
            <button
              type="button"
              className="app-search-trigger"
              aria-label="搜索论文和功能"
              onClick={() => setPaletteOpen(true)}
            >
              <Search aria-hidden="true" />
              <span>搜索</span>
              <span className="kbd" aria-hidden="true">
                {isMac ? "⌘K" : "Ctrl K"}
              </span>
            </button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button type="button" className="account-trigger" aria-label="打开账户菜单">
                  {(email || "我")[0]}
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-64">
                <div className="account-menu-head">
                  <strong>{email || "我的账户"}</strong>
                  <span>EasyPaper 账户</span>
                </div>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => navigate("/settings")}>
                  <Settings />
                  设置
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => logout(navigate)}>
                  <LogOut />
                  退出登录
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </header>
      <main id="workspace-content" className="app-main">
        <Outlet />
      </main>
      <nav className="app-tabbar" aria-label="底部导航">
        {[...links, { to: "/settings", label: "设置", icon: Settings, match: (path: string) => path.startsWith("/settings") }].map(
          ({ to, label, icon: Icon, match }) => (
            <NavLink key={to} to={to} className={() => (match(pathname) ? "active" : "")}>
              <Icon aria-hidden="true" />
              <span>{label}</span>
              {to === "/review" && badge ? <span className="count-badge">{badge}</span> : null}
            </NavLink>
          ),
        )}
      </nav>
      {palette}
    </div>
  );
}
