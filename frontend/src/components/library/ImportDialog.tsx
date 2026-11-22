import { useRef, useState } from "react";
import { ArrowRight, BookOpen, FileText, Languages, Link2, Loader2, MousePointerClick, Upload } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { SegmentedControl } from "@/components/ui/segmented-control";
import api from "@/lib/api";
import { getApiErrorMessage } from "@/lib/errors";
import type { Features } from "@/lib/features";
import { cn } from "@/lib/utils";

export type ImportMode = "translate" | "simplify" | "gloss";
export type ImportResult = { task_id: string; duplicate_of?: string | null };

const MODES: { value: ImportMode; label: string; hint: string; icon: typeof Languages }[] = [
  { value: "translate", label: "中文译文", hint: "保留排版的完整中文翻译", icon: Languages },
  { value: "simplify", label: "简化英文", hint: "常用词改写，难句更好懂", icon: BookOpen },
  { value: "gloss", label: "原文点读", hint: "点词、术语或句式，即看释义", icon: MousePointerClick },
];

export default function ImportDialog({
  open,
  onOpenChange,
  features,
  onImported,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  features: Features;
  onImported: (result: ImportResult, name: string) => void;
}) {
  const [mode, setMode] = useState<ImportMode>("translate");
  const [highlight, setHighlight] = useState(false);
  const [source, setSource] = useState<"file" | "url">("file");
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const [pdfUrl, setPdfUrl] = useState("");
  const [urlLoading, setUrlLoading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const busy = uploadProgress !== null || urlLoading;
  const maxMb = features.max_upload_mb;

  const validateFile = (file: File) => {
    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      toast.error("仅支持 PDF 文件。");
      return false;
    }
    if (file.size > maxMb * 1024 * 1024) {
      toast.error(`文件大小超过 ${maxMb} MB 限制。`);
      return false;
    }
    return true;
  };

  const uploadFile = async (file: File) => {
    if (!features.ai_available) {
      toast.error("AI 服务尚未就绪，请联系管理员。");
      return;
    }
    if (busy || !validateFile(file)) return;
    const form = new FormData();
    form.append("file", file);
    form.append("mode", mode);
    form.append("highlight", String(mode === "gloss" ? false : highlight));
    setUploadProgress(0);
    try {
      const { data } = await api.post<ImportResult>("/api/upload", form, {
        onUploadProgress: (event) => {
          if (event.total) setUploadProgress(Math.round((event.loaded / event.total) * 100));
        },
      });
      onOpenChange(false);
      onImported(data, file.name);
    } catch (error) {
      toast.error(getApiErrorMessage(error, "上传失败。"));
    } finally {
      setUploadProgress(null);
    }
  };

  const submitUrl = async () => {
    if (!features.ai_available || busy) return;
    const trimmed = pdfUrl.trim();
    if (!trimmed) {
      toast.error("请输入 PDF 链接。");
      return;
    }
    try {
      new URL(trimmed.startsWith("http") ? trimmed : `https://${trimmed}`);
    } catch {
      toast.error("请输入有效的链接。");
      return;
    }
    setUrlLoading(true);
    try {
      const { data } = await api.post<ImportResult>("/api/upload-url", {
        url: trimmed,
        mode,
        highlight: mode === "gloss" ? false : highlight,
      });
      setPdfUrl("");
      onOpenChange(false);
      onImported(data, trimmed);
    } catch (error) {
      toast.error(getApiErrorMessage(error, "从链接下载 PDF 失败。"));
    } finally {
      setUrlLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent className="import-dialog">
        <DialogHeader>
          <DialogTitle>导入论文</DialogTitle>
          <DialogDescription>原文始终保留。先选一种阅读方式，其他版本之后也能在阅读器里生成。</DialogDescription>
        </DialogHeader>
        <fieldset disabled={busy}>
          <legend className="import-legend">阅读方式</legend>
          <div className="import-options">
            {MODES.map(({ value, label, hint, icon: Icon }) => (
              <label key={value} className="import-option">
                <input
                  type="radio"
                  name="reading-result"
                  checked={mode === value}
                  onChange={() => setMode(value)}
                  aria-label={label}
                />
                <Icon aria-hidden="true" />
                <span>{label}</span>
                <small>{hint}</small>
              </label>
            ))}
          </div>
        </fieldset>
        <SegmentedControl
          ariaLabel="导入来源"
          value={source}
          onChange={setSource}
          options={[
            { value: "file", label: "PDF 文件", icon: <FileText /> },
            { value: "url", label: "论文链接", icon: <Link2 /> },
          ]}
          className="w-full [&>button]:flex-1"
        />
        {source === "file" ? (
          <div
            className={cn("import-dropzone", dragging && "is-dragging")}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={(event) => {
              event.preventDefault();
              setDragging(false);
            }}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              const file = event.dataTransfer.files?.[0];
              if (file) void uploadFile(file);
            }}
          >
            <div className="import-dropzone-icon" aria-hidden="true">
              <Upload size={22} />
            </div>
            <h3>{dragging ? "松开即可导入" : "把 PDF 拖到这里"}</h3>
            <p>
              也可拖拽到这里 · 最大 {maxMb} MB · {features.max_pages} 页
            </p>
            <Button disabled={!features.ai_available || busy} onClick={() => fileInput.current?.click()}>
              {uploadProgress !== null ? <Loader2 className="spin" /> : <FileText />}
              {uploadProgress !== null ? "正在上传…" : "选择 PDF"}
            </Button>
            <input
              ref={fileInput}
              type="file"
              accept=".pdf,application/pdf"
              hidden
              aria-label="上传 PDF"
              disabled={!features.ai_available}
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file) void uploadFile(file);
              }}
            />
            {uploadProgress !== null && (
              <div className="w-full" role="status" style={{ display: "grid", gap: 6 }}>
                <p>上传文件 {uploadProgress}%</p>
                <Progress value={uploadProgress} />
              </div>
            )}
          </div>
        ) : (
          <form
            className="import-url"
            onSubmit={(event) => {
              event.preventDefault();
              void submitUrl();
            }}
          >
            <label htmlFor="paper-url" className="ui-label" style={{ margin: 0 }}>
              PDF 链接
            </label>
            <div className="import-url-row">
              <Input
                id="paper-url"
                type="url"
                autoFocus
                placeholder="粘贴 arXiv、OpenReview 或 PDF 直链"
                value={pdfUrl}
                onChange={(event) => setPdfUrl(event.target.value)}
                disabled={!features.ai_available || urlLoading}
              />
              <Button type="submit" disabled={!features.ai_available || urlLoading || !pdfUrl.trim()}>
                {urlLoading ? <Loader2 className="spin" /> : <ArrowRight />}
                {urlLoading ? "正在获取…" : "导入"}
              </Button>
            </div>
            {urlLoading ? <Progress /> : null}
          </form>
        )}
        {mode !== "gloss" && (
          <details className="import-optional">
            <summary>可选设置</summary>
            <label>
              <input
                type="checkbox"
                checked={highlight}
                onChange={(event) => setHighlight(event.target.checked)}
                disabled={busy}
              />
              <span>
                生成时自动标注重点
                <br />
                <span className="text-xs">AI 按结论、方法、数据三类着色，供阅读参考；你也可以自己划线。</span>
              </span>
            </label>
          </details>
        )}
        <p className="import-footnote">关闭面板不会取消已提交的任务。</p>
      </DialogContent>
    </Dialog>
  );
}
