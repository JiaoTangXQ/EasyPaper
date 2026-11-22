import { useState, useCallback, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Download, FolderOpen, Loader2, LogOut, Save } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { PageHeader } from "@/components/workspace/PageHeader";
import { cn } from "@/lib/utils";
import api from "@/lib/api";
import { getApiErrorMessage } from "@/lib/errors";
import { useFeatures } from "@/lib/features";
import { EXPORT_FORMATS, exportKnowledge, type ExportFormat } from "@/lib/knowledge-export";
import { normalizeUserPreferences, useUserPreferences, type UserPreferences } from "@/lib/preferences";
import { currentEmail, logout } from "@/lib/session";

interface ObsidianVault {
  name: string;
  path: string;
  exists: boolean;
  writable: boolean;
  open: boolean;
}

export default function Settings() {
  const features = useFeatures();
  const navigate = useNavigate();
  const { preferences, setPreferences, loading: preferencesLoading } = useUserPreferences();
  const [preferencesSaving, setPreferencesSaving] = useState(false);
  const [obsidianVaults, setObsidianVaults] = useState<ObsidianVault[]>([]);
  const [obsidianPath, setObsidianPath] = useState("");
  const [obsidianRootFolder, setObsidianRootFolder] = useState("EasyPaper");
  const [obsidianLoading, setObsidianLoading] = useState(false);
  const [obsidianSaving, setObsidianSaving] = useState(false);
  const [exporting, setExporting] = useState<ExportFormat | null>(null);

  const fetchObsidianSettings = useCallback(async () => {
    if (!features.local_sync) return;
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
  }, [features.local_sync]);

  useEffect(() => {
    void fetchObsidianSettings();
  }, [fetchObsidianSettings]);

  useEffect(() => {
    // Deep links such as /settings#connection-settings scroll once the section exists.
    const id = window.location.hash.slice(1);
    if (id) window.requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ block: "start" }));
  }, [features.loaded]);

  const savePreferences = async (next: UserPreferences, success: string) => {
    const previous = preferences;
    setPreferences(next);
    setPreferencesSaving(true);
    try {
      const { data } = await api.put("/api/settings/preferences", next);
      setPreferences(normalizeUserPreferences(data));
      toast.success(success);
    } catch (error) {
      setPreferences(previous);
      toast.error(getApiErrorMessage(error, "保存阅读设置失败。"));
    } finally {
      setPreferencesSaving(false);
    }
  };
  const updateGloss = (patch: Partial<UserPreferences["reading"]["gloss"]>, success: string) =>
    void savePreferences(
      { ...preferences, reading: { ...preferences.reading, gloss: { ...preferences.reading.gloss, ...patch } } },
      success,
    );

  const handleTestObsidian = async () => {
    if (!obsidianPath.trim()) {
      toast.error("请先选择或填写 Obsidian vault 路径。");
      return;
    }
    setObsidianLoading(true);
    try {
      await api.post("/api/knowledge/settings/obsidian/test", { vault_path: obsidianPath, root_folder: obsidianRootFolder });
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

  const runExport = async (format: ExportFormat, label: string) => {
    setExporting(format);
    try {
      await exportKnowledge(format);
      toast.success(`已导出 ${label}`);
    } catch {
      toast.error("导出失败。");
    } finally {
      setExporting(null);
    }
  };

  const busy = preferencesLoading || preferencesSaving;
  return (
    <div className="page settings-page">
      <PageHeader title="设置" description="阅读偏好、连接与数据导出。" />
      <div className="settings-layout ep-enter">
        <nav className="settings-nav" aria-label="设置分类">
          <a href="#reading-settings">阅读与点读</a>
          <a href="#connection-settings">连接与同步</a>
          <a href="#data-settings">数据与导出</a>
          <a href="#account-settings">账户</a>
        </nav>
        <div className="settings-sections">
          <section id="reading-settings" className="settings-section">
            <h2>阅读与点读</h2>
            <div className="settings-group">
              <div className="settings-option">
                <div>
                  <h3>点读后自动朗读</h3>
                  <p>点击单词或短语时，在打开释义的同时播放英文读音。释义卡片上的喇叭按钮始终可以手动播放。</p>
                </div>
                <Switch
                  checked={preferences.reading.gloss.auto_speak}
                  onCheckedChange={(autoSpeak) =>
                    updateGloss({ auto_speak: autoSpeak }, autoSpeak ? "已开启点读自动朗读。" : "已关闭点读自动朗读。")
                  }
                  disabled={busy}
                  aria-label="点读后自动朗读"
                />
              </div>
              {features.gloss_preparation_site === "user_choice" ? (
                <div className="settings-option settings-option-stack">
                  <div>
                    <h3>点读准备方式</h3>
                    <p>
                      选择点读释义在何处生成。本机处理器需要管理员在服务器配置令牌，并在你的电脑上运行{" "}
                      <code>python -m app.cli gloss-worker</code>。
                      {!features.gloss_worker_configured ? (
                        <span className="settings-warning"> 当前服务器尚未配置本地点读令牌，选「本机」会失败。</span>
                      ) : null}
                    </p>
                  </div>
                  <div className="settings-radio-group" role="radiogroup" aria-label="点读准备方式">
                    {(
                      [
                        ["server", "在服务器上准备（默认）", "点读准备将使用服务器。"],
                        ["remote_worker", "在本机处理器上准备（更快，需保持 worker 运行）", "点读准备将使用本机处理器。"],
                      ] as const
                    ).map(([value, label, success]) => (
                      <label key={value} className="settings-radio">
                        <input
                          type="radio"
                          name="gloss-preparation"
                          checked={preferences.reading.gloss.preparation === value}
                          disabled={busy}
                          onChange={() => updateGloss({ preparation: value }, success)}
                        />
                        {label}
                      </label>
                    ))}
                  </div>
                </div>
              ) : features.gloss_preparation_site === "remote_worker" ? (
                <div className="settings-option">
                  <p className="settings-note">
                    此站点固定使用本地点读处理器准备释义。请在服务器配置 <code>GLOSS_WORKER_TOKEN</code> 并在本机运行 worker。
                  </p>
                </div>
              ) : null}
            </div>
          </section>

          <section id="connection-settings" className="settings-section">
            <h2>连接与同步</h2>
            {features.local_sync ? (
              <>
                <p>保存后可在单篇知识笔记里同步到 Obsidian。路径属于服务运行环境，未必是浏览器所在的设备。</p>
                <div className="settings-group">
                  <div className="settings-option settings-option-stack">
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
                      <h3>Obsidian 笔记库</h3>
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={async () => {
                          setObsidianLoading(true);
                          try {
                            await fetchObsidianSettings();
                          } finally {
                            setObsidianLoading(false);
                          }
                        }}
                        disabled={obsidianLoading}
                      >
                        {obsidianLoading ? <Loader2 className="spin" /> : <FolderOpen />}
                        重新检测
                      </Button>
                    </div>
                    {obsidianVaults.length > 0 && (
                      <div className="settings-vaults">
                        {obsidianVaults.map((vault) => (
                          <button
                            type="button"
                            key={vault.path}
                            className={cn(
                              "settings-vault",
                              obsidianPath === vault.path && "is-selected",
                              (!vault.exists || !vault.writable) && "is-disabled",
                            )}
                            onClick={() => setObsidianPath(vault.path)}
                          >
                            <span style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                              <strong>{vault.name}</strong>
                              <span className={cn("pill", vault.exists && vault.writable ? "is-ok" : "is-danger")}>
                                {vault.exists && vault.writable ? "可写" : "不可写"}
                              </span>
                            </span>
                            <small>{vault.path}</small>
                          </button>
                        ))}
                      </div>
                    )}
                    <div className="settings-fields">
                      <div>
                        <label className="ui-label" htmlFor="obsidian-path">
                          笔记库路径
                        </label>
                        <Input
                          id="obsidian-path"
                          value={obsidianPath}
                          onChange={(event) => setObsidianPath(event.target.value)}
                          placeholder="填写服务运行环境中的笔记库路径"
                        />
                      </div>
                      <div>
                        <label className="ui-label" htmlFor="obsidian-root">
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
                    <div className="settings-actions">
                      <Button variant="secondary" onClick={handleTestObsidian} disabled={obsidianLoading}>
                        {obsidianLoading && <Loader2 className="spin" />}
                        测试写入
                      </Button>
                      <Button onClick={handleSaveObsidian} disabled={obsidianSaving}>
                        {obsidianSaving ? <Loader2 className="spin" /> : <Save />}
                        保存设置
                      </Button>
                    </div>
                  </div>
                </div>
              </>
            ) : (
              <div className="settings-group">
                <div className="settings-option">
                  <div>
                    <h3>Obsidian 笔记</h3>
                    <p>在知识笔记中导出 Obsidian ZIP，解压后放入自己的笔记库。</p>
                  </div>
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={exporting !== null}
                    onClick={() => void runExport("obsidian", "Obsidian 笔记 · ZIP")}
                  >
                    {exporting === "obsidian" ? <Loader2 className="spin" /> : <Download />}
                    导出 ZIP
                  </Button>
                </div>
              </div>
            )}
          </section>

          <section id="data-settings" className="settings-section">
            <h2>数据与导出</h2>
            <p>知识是你的，随时带走。带批注的 PDF 和单篇备份在阅读器的“更多”菜单里导出。</p>
            <div className="settings-group">
              {EXPORT_FORMATS.map(({ format, label, hint }) => (
                <div className="settings-option" key={format}>
                  <div>
                    <h3>{label}</h3>
                    <p>{hint}</p>
                  </div>
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={exporting !== null}
                    aria-label={`导出${label}`}
                    onClick={() => void runExport(format, label)}
                  >
                    {exporting === format ? <Loader2 className="spin" /> : <Download />}
                    导出
                  </Button>
                </div>
              ))}
            </div>
          </section>

          <section id="account-settings" className="settings-section">
            <h2>账户</h2>
            <div className="settings-group">
              <div className="settings-option">
                <div>
                  <h3>{currentEmail() || "当前账户"}</h3>
                  <p>{features.registration ? "已登录。" : "账号由管理员开通；修改密码请联系管理员。"}</p>
                </div>
                <Button variant="secondary" size="sm" onClick={() => logout(navigate)}>
                  <LogOut />
                  退出登录
                </Button>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
