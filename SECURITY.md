# Security and privacy

EasyPaper keeps runtime credentials outside the repository:

- `backend/config/config.yaml` is the local API/JWT/agent configuration. Commit only [`backend/config/config.example.yaml`](backend/config/config.example.yaml).
- `.env` and `.env.*` are ignored; commit only `.env.example`.
- SQLite databases, logs, temporary PDFs, certificates, and local Codex state are ignored.
- The Docker build context excludes the local config, environment files, data, logs, and temporary files.

For Codex mode, authentication is provided by the Codex CLI login belonging to the OS account running the backend. The application does not store a Codex token or copy API keys into the child process environment. Paper text and selected page images are still sent to the Codex account's service when a reading operation runs; choose `llm.provider: "api"` or `llm.provider: "codex"` according to your privacy and retention requirements.

The stock Docker image is configured for the HTTP provider and does not contain a Codex login. To use Codex in Docker, install the CLI in a private image and provide a deliberately mounted Codex home for the backend user; never copy that directory into the image or repository. A host process can use the normal `codex login` flow directly.

Before publishing a branch, run:

```bash
git status --short
git ls-files | rg '(^|/)(\.env|config\.yaml|.*\.(pem|key|p12|pfx)|.*\.(db|sqlite|sqlite3))$'
git grep -n -I -E 'sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{20,}|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY'
```

The first command must not show a local credential file. The second and third commands should return no results for a clean public release. If a real secret has ever been committed, rotate it and rewrite the affected Git history; adding an ignore rule does not remove an old secret from GitHub clones or forks.

## Server deployment

Use [the server deployment guide](docs/DEPLOYMENT.md). Production mode forces
registration, local Obsidian filesystem access and shared Agent/MCP access off.
Passwords reset/disable/enable operations revoke previous sessions. Daily request
quotas are persistent; burst and queue limits require one backend process.

The backend is unprivileged with a read-only root filesystem; persistent PDF data
and the database must be backed up together. Supply a separate AI key with a
provider-side budget, and maintain independent, encrypted backups. Login tokens
are bearer tokens in browser storage, so frontend XSS prevention and HTTPS remain
essential. No configuration can guarantee immunity from attacks or dependency bugs.

Dependency lock files intentionally exclude pdf2zh's unused Gradio UI and override
its outdated PDF parser constraint. Do not install the upstream requirements alone.
