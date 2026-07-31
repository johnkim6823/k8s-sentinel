"""Minimal Kubernetes API client over httpx using the pod service account.

Shared by the context collector (reads) and the remediation executor (writes),
so there is no kubernetes-client dependency. Outside a cluster, set
KUBERNETES_API_URL and optionally KUBERNETES_TOKEN for testing.
"""

import os
from pathlib import Path
from typing import Any

import httpx

SA_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")


def api_base() -> str:
    if url := os.environ.get("KUBERNETES_API_URL"):
        return url
    host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    return f"https://{host}:{port}"


def client() -> httpx.Client:
    headers = {}
    token = os.environ.get("KUBERNETES_TOKEN")
    if not token and (SA_DIR / "token").exists():
        token = (SA_DIR / "token").read_text().strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    ca = SA_DIR / "ca.crt"
    verify: bool | str = str(ca) if ca.exists() else False
    return httpx.Client(base_url=api_base(), headers=headers, verify=verify, timeout=10.0)


def get(path: str, params: dict | None = None) -> dict[str, Any]:
    with client() as c:
        resp = c.get(path, params=params)
        resp.raise_for_status()
        return resp.json()


def patch(path: str, body: dict, content_type: str) -> dict[str, Any]:
    with client() as c:
        resp = c.patch(path, json=body, headers={"Content-Type": content_type})
        resp.raise_for_status()
        return resp.json()


def post(path: str, body: dict) -> dict[str, Any]:
    with client() as c:
        resp = c.post(path, json=body)
        resp.raise_for_status()
        return resp.json()
