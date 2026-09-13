import { useState, useCallback, useEffect } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/workspace/PageHeader";
import { FolderOpen, Loader2, Save, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import api from "@/lib/api";
import { getApiErrorMessage } from "@/lib/errors";
interface ObsidianVault {
  name: string;
  path: string;
  exists: boolean;
  writable: boolean;
  open: boolean;
}

export default function Settings() {
  const [obsidianVaults, setObsidianVaults] = useState<ObsidianVault[]>([]);
  const [obsidianPath, setObsidianPath] = useState("");
  const [obsidianRootFolder, setObsidianRootFolder] = useState("EasyPaper");
  const [obsidianLoading, setObsidianLoading] = useState(false);
  const [obsidianSaving, setObsidianSaving] = useState(false);
  const fetchObsidianSettings = useCallback(async () => {
    try {
      const [settingsResponse, vaultsResponse] = await Promise.all([
        api.get("/api/knowledge/settings/obsidian"),
        api.get("/api/knowledge/settings/obsidian/vaults"),
      ]);
      const vaults = vaultsResponse.data.vaults || [];
      setObsidianVaults(vaults);
      setObsidianPath(
        settingsResponse.data.vault_path ||
          vaults.find((vault: ObsidianVault) => vault.exists && vault.writable)?.path ||
          "",
      );
      setObsidianRootFolder(settingsResponse.data.root_folder || "EasyPaper");
    } catch {
      toast.error("无法加载连接设置，请重新检测。");
    }
  }, []);

  useEffect(() => {
    void fetchObsidianSettings();
  }, [fetchObsidianSettings]);
  const handleRefreshObsidianVaults = async () => {
    setObsidianLoading(true);
    try {
      await fetchObsidianSettings();
    } finally {
      setObsidianLoading(false);
    }
  };

  const handleTestObsidian = async () => {
    if (!obsidianPath.trim()) {
      toast.error("请先选择或填写 Obsidian vault 路径。");
      return;
    }
    setObsidianLoading(true);
    try {
      await api.post("/api/knowledge/settings/obsidian/test", {
        vault_path: obsidianPath,
        root_folder: obsidianRootFolder,
      });
      toast.success("Obsidian 目录可写。");
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Obsidian 写入测试失败。"));
    } finally {
      setObsidianLoading(false);
    }
  };

  const handleSaveObsidian = async () => {
    if (!obsidianPath.trim()) {
      toast.error("请先选择或填写 Obsidian vault 路径。");
      return;
    }
    setObsidianSaving(true);
    try {
      const response = await api.post("/api/knowledge/settings/obsidian", {
        vault_path: obsidianPath,
        root_folder: obsidianRootFolder,
      });
      setObsidianPath(response.data.vault_path);
      setObsidianRootFolder(response.data.root_folder || "EasyPaper");
      toast.success("Obsidian 设置已保存。");
    } catch (error) {
      toast.error(getApiErrorMessage(error, "保存 Obsidian 设置失败。"));
    } finally {
      setObsidianSaving(false);
    }
  };

  return (
    <div className="page-stack settings-page">
      <PageHeader title="连接设置" description="将阅读成果保留在自己的知识工具中。" />{" "}
      <section className="space-y-5 rounded-xl border bg-white p-5 sm:p-7">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">Obsidian 笔记同步</h2>
            <p className="text-sm text-muted-foreground">
              保存后可在单篇知识页同步笔记。路径属于服务运行环境，未必是浏览器所在设备。
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={handleRefreshObsidianVaults}
            disabled={obsidianLoading}
          >
            {obsidianLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderOpen className="h-4 w-4" />}
            重新检测
          </Button>
        </div>

        {obsidianVaults.length > 0 && (
          <div className="grid gap-2 md:grid-cols-2">
            {obsidianVaults.map((vault) => (
              <button
                type="button"
                key={vault.path}
                className={cn(
                  "rounded-lg border p-3 text-left transition-colors",
                  obsidianPath === vault.path ? "border-primary bg-primary/5" : "border-gray-200 hover:border-gray-300",
                  (!vault.exists || !vault.writable) && "opacity-60",
                )}
                onClick={() => setObsidianPath(vault.path)}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{vault.name}</span>
                  <span
                    className={cn(
                      "rounded-full px-2 py-0.5 text-xs",
                      vault.exists && vault.writable ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700",
                    )}
                  >
                    {vault.exists && vault.writable ? "可写" : "不可写"}
                  </span>
                </div>
                <p className="mt-1 break-all text-xs text-muted-foreground">{vault.path}</p>
              </button>
            ))}
          </div>
        )}

        <div className="grid gap-3 md:grid-cols-[1fr_220px]">
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="obsidian-path">
              笔记库路径
            </label>
            <Input
              id="obsidian-path"
              value={obsidianPath}
              onChange={(event) => setObsidianPath(event.target.value)}
              placeholder="填写服务运行环境中的笔记库路径"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="obsidian-root">
              同步目录
            </label>
            <Input
              id="obsidian-root"
              value={obsidianRootFolder}
              onChange={(event) => setObsidianRootFolder(event.target.value)}
              placeholder="EasyPaper"
            />
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button variant="outline" className="gap-2" onClick={handleTestObsidian} disabled={obsidianLoading}>
            {obsidianLoading && <Loader2 className="h-4 w-4 animate-spin" />}
            测试写入
          </Button>
          <Button className="gap-2" onClick={handleSaveObsidian} disabled={obsidianSaving}>
            {obsidianSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            保存设置
          </Button>
        </div>
      </section>
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">导出与备份</h2>
        <p className="text-sm text-muted-foreground">
          在知识笔记中导出 JSON 备份、Obsidian 笔记、BibTeX / CSL-JSON 引用及 CSV 表格。带批注 PDF 在阅读器内导出。
        </p>
        <Button variant="outline" asChild>
          <Link to="/knowledge">
            前往知识笔记
            <ArrowRight />
          </Link>
        </Button>
      </section>
    </div>
  );
}
