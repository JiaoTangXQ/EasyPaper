#!/usr/bin/env python3
"""Create server secrets once. Does not deploy, overwrite config, or print secrets."""
import argparse
import ipaddress
import os
import re
import secrets
from pathlib import Path


def prepare(root: Path, domain: str, *, behind_proxy: bool = False):
    domain = domain.strip().lower()
    try:
        address = ipaddress.IPv4Address(domain)
    except ValueError:
        if not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain):
            raise ValueError("请输入域名，例如 papers.example.com，不包含协议或路径")
    else:
        if not address.is_global or not behind_proxy:
            raise ValueError("公网 IPv4 访问需要 --behind-proxy，并在现有代理上配置覆盖该 IP 的公共可信 HTTPS 证书")
    target = root / ".env"
    content = f"""# Generated locally; never commit or paste this file into chat.
DOMAIN={domain}
BIND_IP={"127.0.0.1" if behind_proxy else "0.0.0.0"}
POSTGRES_PASSWORD={secrets.token_hex(32)}
EASYPAPER_SECRET_KEY={secrets.token_hex(32)}
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
BACKEND_MEMORY=4g
BACKEND_CPUS=2
"""
    if behind_proxy:
        content += "HTTP_PORT=18081\nHTTPS_PORT=18444\nCADDY_SITE_ADDRESS=:80\n"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(content)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    parser.add_argument("--behind-proxy", action="store_true", help="由现有 HTTPS 代理接入，仅绑定本机端口")
    args = parser.parse_args()
    try:
        result = prepare(Path(__file__).resolve().parents[1], args.domain, behind_proxy=args.behind_proxy)
        print(f"已生成 {result}（权限 600）。填入 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 后即可部署。")
    except (ValueError, FileExistsError) as error:
        parser.error(str(error))
