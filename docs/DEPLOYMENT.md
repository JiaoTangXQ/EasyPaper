# 阿里云 ECS：5 人私有部署

这套配置适合一台 Linux ECS，使用 Docker Compose、PostgreSQL 和 Caddy HTTPS。
每个人使用管理员创建的独立账号。生产模式强制关闭公开注册、Agent/MCP
接口和服务器本地 Obsidian 同步；Obsidian ZIP 导出仍可使用。

## 部署前核对

- 推荐起步：Ubuntu 24.04 / Debian 12，x86_64 或 ARM64，4 核、8 GB 内存、
  至少 40 GB 可用磁盘。这是保守配置建议，不是压测承诺。4 GB 机器需要下调
  `BACKEND_MEMORY`，并实测 PDF 翻译峰值内存；默认只并行处理 1 份 PDF。
- 已安装 Docker Engine 和 Compose v2（支持 `--wait`）。
- 一个域名，A 记录指向 ECS 公网地址；只有确实可用时才配置 AAAA。
- 如果服务器在中国内地并提供公网网站，先核实域名备案要求。
  [阿里云建站流程](https://www.alibabacloud.com/help/en/dws/getting-started/the-whole-process-of-website-building/)
- 安全组只开放 TCP 80/443；SSH 22 仅允许管理员 IP。不要开放 8000、5432
  或 Docker API。Docker 发布端口可能绕过主机上的部分防火墙规则，应同时核对
  阿里云安全组和实际端口监听。
  [阿里云安全组建议](https://www.alibabacloud.com/help/en/ecs/user-guide/security-groups-for-different-use-cases)
- 服务器必须能访问选定的 AI 接口，以及首次运行下载模型和字体所需的站点。
  先验证可达性，不默认阿里云内地节点能直接连接所有海外服务。

## 初始化（只运行一次）

在项目根目录：

```bash
python3 scripts/prepare_server.py --domain papers.example.com
```

脚本生成权限为 `600` 的 `.env` 和随机数据库/JWT 密钥，已存在时拒绝覆盖。
编辑 `.env`，填写 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。不要把该文件
发到聊天中或提交到 Git。API Key 建议单独创建，并在供应商侧设置消费上限。
数据库密码使用生成的十六进制值，避免 URL 特殊字符需要转义的问题。

服务器设置位于 `deploy/config.production.yaml`，与本地开发配置独立。
生产镜像默认使用 HTTP API 模式；不自带 Codex 登录态。下节提供服务器已有
Codex 登录时的接入方式。

未填写 AI 配置时也可以先启动网站、创建账号。首页会提示 AI 尚未配置，
导入、翻译和问答请求返回 503；登录和已有论文阅读保持可用。
这只是基础服务上线，必须补齐接口配置并完成真实论文翻译后才能验收全部功能。
填好 `.env` 后执行 `docker compose -f docker-compose.prod.yml up -d --no-build backend`
使配置生效。

## 使用服务器上的 Codex

可以复用服务器已经登录的 Codex CLI，通过 `codex exec` 完成翻译和问答。
网站账号仍各自隔离，但共用这个 Codex 账号的额度。登录成功只表示本机有凭据，
还必须在受限容器中完成一次真实模型调用，才能启用网站入口。
参见 [官方认证说明](https://learn.chatgpt.com/docs/auth) 和
[非交互调用](https://learn.chatgpt.com/docs/non-interactive-mode)。

`deploy/compose.codex.yml` 将宿主机的 Linux Codex 原生运行文件只读挂到容器。
不挂载 `/root`、其他用户目录或 Docker socket，不让 Web 请求在宿主机执行命令。
后端仍以 UID 10001 运行，保留内存上限、只读根目录和原来的权限限制。
Codex 使用独立临时工作目录、无持久会话、只读沙箱，关闭 shell、code mode、
插件、Hooks、浏览器等工具；接收到工具执行事件时终止本次请求。

先在 `.env` 添加（原生目录取决于宿主机的安装路径和 CPU 架构）：

```dotenv
CODEX_RUNTIME_DIR=/usr/local/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl
CODEX_MODEL=gpt-5.5
COMPOSE_FILE=docker-compose.prod.yml:deploy/compose.codex.yml
```

该目录必须同时包含 `bin/codex` 与配套资源。安装在 ARM64 主机时使用对应的
Linux ARM64 目录。此方式直接使用原生程序，不要求后端镜像安装 Node.js。
仅将 `auth.json` 通过服务器本机管道预置到后台私有持久卷的
`/home/app/.codex/auth.json`，目录归属 10001:10001、权限 700，文件权限 600。
不要将登录凭据写入镜像、代码、聊天或命令行参数。凭据应可由 Codex 原地刷新，
不要定期用旧文件覆盖；如登录失效，需要重新登录后更新凭据。

必须先完成隔离容器中的真实调用。未通过时保持现有 API 模式，避免网站报告 AI
已经可用。通过后，启用及以后升级这个模式都使用两个 Compose 文件。Linux 服务器上的
`COMPOSE_FILE` 也让不带 `-f` 的 `docker compose` 保留 Codex 配置；显式指定
`-f` 会覆盖此设置，因此不要在升级时只传基础文件：

```bash
docker compose -f docker-compose.prod.yml -f deploy/compose.codex.yml config --quiet
docker compose -f docker-compose.prod.yml -f deploy/compose.codex.yml up -d --no-build --wait
```

Codex 并发为 1、每次调用最多 180 秒、推理强度 low；不修改宿主机 CLI 的模型
或个人配置。网站读取 `CODEX_MODEL`，显式填写时不会悄悄切换到 CLI 的默认模型。
宿主机升级 Codex 后，需要使用上述两个配置文件重建后端容器，使只读挂载指向新版本。
凭据和登录缓存不属于论文备份，全新机器恢复后需要单独重新授权。

启用后还需真实测试 PDF 排版模型及字体下载、小论文翻译、问答和峰值内存；不能
仅凭 `codex --version` 或 `codex login status` 认为网站已经可以翻译。

## 同一台 ECS 已经运行其他网站

保留现有 Nginx 和网站，新建独立域名的虚拟主机。EasyPaper 的 Caddy 只绑定
本机端口，由现有 Nginx 处理公网 HTTPS。初始化时添加 `--behind-proxy`，
或在已有 `.env` 中设置：

```dotenv
BIND_IP=127.0.0.1
HTTP_PORT=18081
HTTPS_PORT=18444
CADDY_SITE_ADDRESS=:80
```

先确认这两个本机端口空闲。容器启动后运行
`docker network inspect easypaper_app --format '{{(index .IPAM.Config 0).Gateway}}'`，
将返回的实际网关加 `/32` 写入 `CADDY_TRUSTED_PROXIES`，重建 Caddy。
该设置只信任宿主机代理；不要填写 `0.0.0.0/0`。
`deploy/nginx.shared-host.conf.example` 提供独立虚拟主机模板，替换域名和证书路径后，
先执行 `nginx -t`，再平滑重载 Nginx。公网 Nginx 必须覆盖客户端传入的
`X-Forwarded-For`，Caddy 再将解析后的单个客户端 IP 传给后端，确保按 IP 的限流有效。
参见 [Caddy 可信代理说明](https://caddyserver.com/docs/caddyfile/options#trusted-proxies)。

如果现有代理已经持有覆盖公网 IPv4 地址的公共可信证书，`--domain` 也可以填写该
IPv4 地址，但必须同时使用 `--behind-proxy`。在现有 Nginx 上添加独立的 HTTPS
监听端口（例如 8443），复用该 IP 证书及其续期机制，入口为 `https://公网IP:8443/`。
先核对证书 SAN、有效期、续期任务，以及该端口的安全组规则；不要覆盖已有的 443
虚拟主机。没有可用 IP 证书时仍使用域名方案，不能把明文 HTTP 当作公网登录入口。

只有在已核对其他程序内存和交换空间后，2 GB 共享主机才可先用以下限制试运行：

```dotenv
DATABASE_MEMORY=256m
BACKEND_MEMORY=1g
BACKEND_CPUS=1
BACKEND_TMPFS_SIZE=192m
```

同时将 `deploy/config.production.yaml` 中 `max_pages` 降到 30、`max_upload_mb`
降到 15、`max_pending` 降到 3、`max_pending_per_user` 降到 1，保留 PDF 并发为 1。
这些是资源上限，不能保证大型论文不会触发内存限制；必须实测目标 PDF 和模型。
镜像在其他机器上按 ECS 的 CPU 架构构建，避免在小内存 ECS 上编译。
部署后仍须保留至少 2 GB 可用磁盘以及增长空间，不自动清理其他应用的镜像或数据卷。

## 启动与账号管理

```bash
docker compose -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.prod.yml up --build -d --wait --wait-timeout 300

docker compose -f docker-compose.prod.yml exec backend python -m app.cli create-user alice@example.com
```

重复创建其余 4 个账号。密码交互输入，至少 12 个字符、最多 72 个 UTF-8 字节。
不要把密码作为命令行参数。账号总数默认最多 5 个（含停用账号）；如需调整，修改
`security.max_users` 并重启后端。

```bash
docker compose -f docker-compose.prod.yml exec backend python -m app.cli list-users
docker compose -f docker-compose.prod.yml exec backend python -m app.cli reset-password alice@example.com
docker compose -f docker-compose.prod.yml exec backend python -m app.cli disable-user alice@example.com
docker compose -f docker-compose.prod.yml exec backend python -m app.cli enable-user alice@example.com
```

重置密码、停用、重新启用都会使该账号之前签发的登录凭证失效。
修改 JWT 密钥并重建容器会让所有人重新登录。

## 验收

1. `https://你的域名` 能正常登录，浏览器证书有效，HTTP 跳转 HTTPS。
2. 登录页没有注册入口；直接请求 `/api/auth/register` 返回 403。
3. 未登录请求 `/api/upload` 返回 401；`/mcp`、`/api/agent/v1/translate` 返回 404。
4. A 上传一篇小 PDF，B 无法读取、下载或删除 A 的任务；再验证各自的批注和导出。
5. 翻译一篇实际论文，验证模型/字体下载、中文显示、阅读器 WASM 和所有 PDF 版本。
6. 同时由 5 个账号阅读，提交超过 2 个同账号翻译任务应返回 429。
7. 从服务器外确认 8000/5432 不可达。检查 `docker stats`、磁盘余量和日志。
8. 创建备份，执行校验，并在独立测试实例恢复；确认论文和批注可读取。

未完成这些步骤不能认为远程部署已验收。当前后端使用单进程，请勿增加
uvicorn `--workers` 或直接启动多个后端副本；队列和短时限流依赖单进程。

## 限额和资源

默认单文件 30 MB、100 页，每人每日 20 次导入、300 次其他 POST/PUT 操作。
每日额度按 **UTC 零点** 重置，存在数据库中，服务重启不会清零。失败但已接纳的请求
也计数；查询、删除、保存阅读位置和取消任务不消耗每日操作额度。
这些是请求额度，不是精确的 AI token/费用账单；一个请求可能调用模型多次。

上传和知识提取共用最多 6 个待处理名额，每人最多 2 个；阅读器版本生成也共用该
队列。划线对齐另有有界队列。PDF 翻译并发默认为 1。请求体在读取期间限量，
下载连接固定到已校验的公网 IP，屏蔽内网、云元数据和特殊网段。

后端以 UID/GID 10001 运行，只读系统目录，只允许写入数据卷和受限临时目录。
首次从旧 root 镜像升级时，须先备份，再把现有应用数据卷归属调整为 10001:10001；
不要修改 PostgreSQL 数据卷归属。**绝不能通过 `down -v` 解决权限或升级问题。**

## 备份与恢复

备份包含 PostgreSQL、`/app/tmp` 中的原始/生成 PDF、永久版本库，以及服务器配置。
模型缓存和日志可重建，不属于用户数据。备份会短暂停止后端，保障数据库和文件一致；
未完成的生成会在启动后标记为可重试。

```bash
python3 scripts/server_backup.py backup /srv/easypaper-backups
python3 scripts/server_backup.py verify /srv/easypaper-backups/easypaper-时间戳
```

目录权限 700、文件权限 600。备份含密钥，不可放在 Web 静态目录。成功目录包含
校验清单；失败备份保留在 `.incomplete-*` 中，排查后再清理。

定时任务示例（服务器本地时间 03:15；机器时区需在部署时核对）：

```cron
15 3 * * * cd /srv/EasyPaper && /usr/bin/python3 scripts/server_backup.py backup /srv/easypaper-backups >> /var/log/easypaper-backup.log 2>&1
```

上线时还要配置独立位置的备份，例如启用私有访问、版本控制和保留策略的 OSS Bucket。
**仅存在同一台 ECS 的备份不能防范服务器或账号失陷。** 上传前加密，使用仅有备份
写入权限的 RAM 身份；密钥和恢复凭据另行保存。脚本没有默认上传到任何外部账户，
OSS 目的地、加密方式、保留天数及告警在实际部署时配置。

恢复会覆盖数据库中的数据，先核对目标实例；脚本会自动再备份当前状态。

```bash
python3 scripts/server_backup.py restore /srv/easypaper-backups/easypaper-时间戳 \
  --safety-backup-dir /srv/easypaper-before-restore --confirm-replace
```

恢复失败时后端保持停止，先排查错误，避免服务读取不一致的数据。
备份中的 `.env` 不会自动覆盖当前服务器配置；全新服务器灾难恢复时先人工恢复配置、
启动数据库，并建立数据卷。当前脚本保留不再被数据库引用的旧 PDF 文件，不自动清空数据卷。

## 更新和回滚

更新前备份并记录当前代码版本及镜像 ID，再构建新镜像，确认空闲后重启。
此次增加的账号登录版本列支持自动、非破坏性迁移；其他已有表的未来结构变化仍需
明确的数据库迁移方案，不能假设 `create_all()` 会升级已有表。

```bash
docker compose -f docker-compose.prod.yml logs --tail 100 backend
docker compose -f docker-compose.prod.yml up --build -d --wait --wait-timeout 300
```

回滚代码/镜像前先确认数据库兼容性；必要时用更新前的完整备份恢复。

使用 Codex 的服务器，更新和回滚都必须同时载入覆盖文件。显式指定单个 `-f`
会覆盖 `.env` 中的 `COMPOSE_FILE`，导致 Codex 配置与挂载丢失：

```bash
docker compose -f docker-compose.prod.yml -f deploy/compose.codex.yml up -d --no-build --wait --wait-timeout 300
```

本实例采用 `/opt/easypaper/releases/` 中的独立发布目录，`/opt/easypaper/current`
指向当前版本。每次发布保留服务端 `.env`、生产配置和已有数据卷，重新构建前端与后端，
健康检查通过后切换链接。`deploy/release.json` 记录 GitHub 提交、实际文件校验值、
镜像标签、上一发布目录和升级前备份，便于核对线上版本及回滚。
2 GiB 服务器保持 `processing.translation_threads: 1`；当前生产上传/远程下载上限为
`max_upload_mb: 50`，页数和并发上限不会随新版默认值改变。

远程 PDF 下载超时为 240 秒，以适配 3 Mbps 服务器下载 50 MB 文件的时间；
支持 Range 的源站使用 4 MiB 分段、独立连接和失败重试。若 ECS 直连出口被学术
站点限速，可在服务器 `.env` 中显式设置 `EASYPAPER_DOWNLOAD_PROXY`；当前生产值为
`http://172.18.0.1:7894`，该代理只绑定 EasyPaper Docker 网桥，不开放公网。
公网入口的反向代理读取超时为 300 秒。

## 本地点读处理器（第二条 gloss 链路）

默认链路仍在 **服务器 backend** 内调用 AI 准备点读（`processing.gloss_preparation: server`）。
若希望 **网页提交任务、在本机高性能电脑准备 gloss、结果回传服务器供其它设备阅读**，
启用第二条链路：

1. 在服务器 `.env` 或 `deploy/config.production.yaml` 设置：
   - `EASYPAPER_GLOSS_PREPARATION=user_choice`（让用户在「设置」里选择）或 `remote_worker`（强制本机）
   - `GLOSS_WORKER_TOKEN=` 使用 `openssl rand -hex 32` 生成，**仅写入服务器与本机 worker，勿提交 Git**
2. 重新部署 backend 使配置生效。
3. 在本机（与服务器网络可达）安装与线上一致的 backend 依赖，配置 **本地 AI**（API Key 或 Cursor/Codex）。
4. 运行 worker。macOS 推荐 **LaunchAgent 自启**（登录后常驻、崩溃自动拉起）：

```bash
# 令牌写入 ~/.config/easypaper/gloss-worker.token（与服务器 GLOSS_WORKER_TOKEN 相同，chmod 600）
chmod +x deploy/macos/install-gloss-worker-launchd.sh deploy/macos/gloss-worker-run.sh
./deploy/macos/install-gloss-worker-launchd.sh
# 日志：~/Library/Logs/EasyPaper/gloss-worker.{out,err}.log
# 停用：launchctl bootout gui/$(id -u)/com.easypaper.gloss-worker
```

临时前台调试仍可用：

```bash
cd backend
export GLOSS_WORKER_TOKEN='与服务器相同'
export EASYPAPER_SERVER_URL='https://你的域名'
export EASYPAPER_GLOSS_CONCURRENCY=4   # 按本机内存调整
python -m app.cli gloss-worker --base-url "$EASYPAPER_SERVER_URL" --token "$GLOSS_WORKER_TOKEN"
```

用户在网站导入 **点读（gloss）** 论文后，任务会先 **索引 PDF 并排队**；worker 领取任务、下载原文包、
在本机跑 `prepare_gloss`，完成后上传 spans。其它电脑打开同一账号即可阅读点读结果。

- **旧链路保留**：`gloss_preparation: server` 时行为与升级前一致。
- **生产安全**：worker 接口仅接受 `Authorization: Bearer <GLOSS_WORKER_TOKEN>`；令牌泄露等同于允许代写点读数据，请轮换令牌并限制网络访问。
- **租约**：默认 900 秒，worker 处理期间会 heartbeat；服务器重启后未完成任务会重新排队。

## 本机知识整理处理器（第二条 knowledge 链路）

默认仍在 **服务器 backend** 内调用 AI 整理知识（`processing.knowledge_preparation: server`）。
仅在你愿意把 LLM 算力放到一台受信任的本机时，可启用第二条链路（与点读 worker 独立）：

1. 服务器 `.env`：
   - `EASYPAPER_KNOWLEDGE_PREPARATION=remote_worker`
   - `KNOWLEDGE_WORKER_TOKEN=`（`openssl rand -hex 32`，勿提交 Git；可与 `GLOSS_WORKER_TOKEN` 相同以简化本机配置）
2. 重新部署 backend。
3. 本机配置本地 AI（API 或 Cursor），并发建议：
   - `EASYPAPER_KNOWLEDGE_CONCURRENCY=6`（篇内 chunk 并行）
   - `EASYPAPER_CURSOR_MAX_CONCURRENT=4`（本机 Cursor 槽位）
4. macOS LaunchAgent 默认已改为 `local-worker`，同时轮询点读与知识任务；也可单独运行
   `python -m app.cli knowledge-worker`。

用户在「知识库」点击 **开始整理** 后，服务器仅排队并下发 PDF；本机跑完整提取流水线并回传 JSON。
未设置 `EASYPAPER_KNOWLEDGE_PREPARATION=remote_worker` 时，GitHub 默认自托管部署行为与升级前一致。

## 阿里云镜像下载缓慢时

可在可联网的构建机器上，按 ECS 架构构建镜像，推送到你自己的阿里云 ACR 私有仓库。
在 `.env` 设置 `BACKEND_IMAGE`、`FRONTEND_IMAGE`（基础服务也支持 `POSTGRES_IMAGE`、
`CADDY_IMAGE`），服务器登录仓库后：

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d --no-build --wait --wait-timeout 300
```

不要随意使用未知公共镜像代理或把 Docker 守护进程暴露到公网。仅有 IP 尚无域名时，
先用 SSH 隧道或私有网络验证，暂不开放明文公网登录。

## Python 依赖维护

运行镜像安装 `backend/requirements.lock`；开发与 CI 安装 `requirements-dev.lock`。
使用 uv 0.12.13 的覆盖和排除文件重新生成锁文件：

```bash
cd backend
uv pip compile requirements.txt --overrides requirements-overrides.txt --excludes requirements-excludes.txt --universal --python-version 3.11 -o requirements.lock
uv pip compile requirements-dev.txt --overrides requirements-overrides.txt --excludes requirements-excludes.txt --universal --python-version 3.11 -o requirements-dev.lock
uv pip sync --python .venv/bin/python requirements-dev.lock
```

PDF 翻译依赖仍使用 pdf2zh 1.9.11 的渲染接口，但覆盖它锁定的旧 PDF 解析依赖，
并移除没有使用的 Gradio Web UI 依赖。每次更新需运行实际 PDF 渲染兼容性测试；
`pip install -r requirements.txt` 会重新引入上游旧依赖，不是服务器安装方式。
