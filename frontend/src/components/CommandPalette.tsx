import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useNavigate } from "react-router-dom";
import {
  ArrowDown,
  ArrowUp,
  BookOpen,
  CornerDownLeft,
  FileText,
  GraduationCap,
  Languages,
  Library,
  LogOut,
  Network,
  NotebookPen,
  Plus,
  Search,
  Settings,
} from "lucide-react";
import api from "@/lib/api";
import { logout } from "@/lib/session";

type Command = {
  id: string;
  group: string;
  label: string;
  hint?: string;
  icon: ReactNode;
  keywords?: string;
  run: () => void;
};
type TaskSummary = { task_id: string; filename: string; title?: string | null; title_zh?: string | null };

/** ⌘K launcher: jump to any paper, page or action without hunting through menus. */
export default function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="ui-overlay" />
        <Dialog.Content className="ui-dialog command-dialog" aria-describedby={undefined}>
          <Dialog.Title className="sr-only">搜索论文和功能</Dialog.Title>
          {/* Content unmounts on close, so every opening starts from an empty query. */}
          <PaletteBody close={() => onOpenChange(false)} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function PaletteBody({ close }: { close: () => void }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [papers, setPapers] = useState<TaskSummary[]>([]);
  const list = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    void api
      .get<TaskSummary[]>("/api/tasks")
      .then(({ data }) => {
        if (!cancelled) setPapers(data);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const commands = useMemo<Command[]>(() => {
    const go = (path: string) => () => navigate(path);
    const pages: Command[] = [
      { id: "import", group: "操作", label: "导入论文", hint: "PDF 文件或论文链接", icon: <Plus />, keywords: "上传 upload import pdf arxiv", run: go("/dashboard?import=1") },
      { id: "review", group: "操作", label: "复习知识卡片", icon: <GraduationCap />, keywords: "复习 flashcard review", run: go("/review") },
      { id: "review-terms", group: "操作", label: "复习术语", icon: <Languages />, keywords: "术语 单词 term vocabulary", run: go("/review?deck=terms") },
      { id: "library", group: "前往", label: "我的论文", icon: <Library />, keywords: "论文 library dashboard", run: go("/dashboard") },
      { id: "knowledge", group: "前往", label: "知识笔记", icon: <NotebookPen />, keywords: "笔记 notes knowledge", run: go("/knowledge") },
      { id: "graph", group: "前往", label: "概念图谱", icon: <Network />, keywords: "图谱 graph 概念 关系", run: go("/knowledge/graph") },
      { id: "terms", group: "前往", label: "术语本", icon: <BookOpen />, keywords: "术语 词表 terms", run: go("/knowledge/terms") },
      { id: "settings", group: "前往", label: "设置", icon: <Settings />, keywords: "设置 settings 导出 export obsidian", run: go("/settings") },
      { id: "logout", group: "账户", label: "退出登录", icon: <LogOut />, keywords: "logout 退出", run: () => logout(navigate) },
    ];
    const paperCommands: Command[] = papers.map((paper) => ({
      id: `paper:${paper.task_id}`,
      group: "论文",
      label: paper.title?.trim() || paper.filename,
      hint: paper.title_zh || (paper.title ? paper.filename : undefined),
      icon: <FileText />,
      keywords: `${paper.filename} ${paper.title_zh || ""}`,
      run: go(`/reader/${paper.task_id}`),
    }));
    return [...pages, ...paperCommands];
  }, [navigate, papers]);

  const results = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return commands.filter((command) => command.group !== "论文").concat(commands.filter((c) => c.group === "论文").slice(0, 6));
    return commands
      .map((command) => {
        const haystack = `${command.label} ${command.hint || ""} ${command.keywords || ""}`.toLocaleLowerCase();
        const index = haystack.indexOf(needle);
        return { command, score: index < 0 ? -1 : index === 0 ? 0 : command.label.toLocaleLowerCase().includes(needle) ? 1 : 2 };
      })
      .filter((item) => item.score >= 0)
      .sort((a, b) => a.score - b.score)
      .map((item) => item.command);
  }, [commands, query]);

  useEffect(() => {
    list.current?.querySelector<HTMLElement>(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const run = (command: Command | undefined) => {
    if (!command) return;
    close();
    command.run();
  };

  let lastGroup = "";
  return (
    <>
          <div className="command-input">
            <Search aria-hidden="true" />
            <input
              autoFocus
              role="combobox"
              aria-expanded="true"
              aria-controls="command-results"
              aria-activedescendant={results[active] ? `command-${results[active].id}` : undefined}
              aria-label="搜索论文和功能"
              placeholder="搜索论文、页面或操作…"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setActive(0);
              }}
              onKeyDown={(event) => {
                if (event.nativeEvent.isComposing) return;
                if (event.key === "ArrowDown") {
                  event.preventDefault();
                  setActive((index) => Math.min(results.length - 1, index + 1));
                } else if (event.key === "ArrowUp") {
                  event.preventDefault();
                  setActive((index) => Math.max(0, index - 1));
                } else if (event.key === "Enter") {
                  event.preventDefault();
                  run(results[active]);
                }
              }}
            />
          </div>
          <div className="command-list" id="command-results" role="listbox" aria-label="搜索结果" ref={list}>
            {results.length ? (
              results.map((command, index) => {
                const heading = command.group !== lastGroup ? command.group : "";
                lastGroup = command.group;
                return (
                  <div key={command.id} role="presentation">
                    {heading ? (
                      <div className="command-group-label" role="presentation">
                        {heading}
                      </div>
                    ) : null}
                    <button
                      type="button"
                      id={`command-${command.id}`}
                      role="option"
                      data-index={index}
                      aria-selected={index === active}
                      className="command-item"
                      onMouseMove={() => setActive(index)}
                      onClick={() => run(command)}
                    >
                      <span className="command-item-icon" aria-hidden="true">
                        {command.icon}
                      </span>
                      <span className="command-item-text">
                        <strong>{command.label}</strong>
                        {command.hint ? <span className="command-item-hint">{command.hint}</span> : null}
                      </span>
                    </button>
                  </div>
                );
              })
            ) : (
              <p className="command-empty">没有找到“{query}”。试试论文标题里的其他词。</p>
            )}
          </div>
          <div className="command-footer" aria-hidden="true">
            <span>
              <kbd>
                <ArrowUp size={11} />
              </kbd>
              <kbd>
                <ArrowDown size={11} />
              </kbd>
              选择
            </span>
            <span>
              <kbd>
                <CornerDownLeft size={11} />
              </kbd>
              打开
            </span>
            <span>
              <kbd>esc</kbd>
              关闭
            </span>
          </div>
    </>
  );
}
