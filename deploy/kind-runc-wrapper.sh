#!/usr/bin/env bash
# runc wrapper for sandboxed/nested-Docker hosts (see deploy/kind-config.yaml).
#
# Some sandboxed environments drop CAP_SYS_RESOURCE, so writing a negative
# oom_score_adj is denied kernel-wide. kubelet asks for oomScoreAdj -998/-997
# on sandbox/guaranteed containers, which makes runc's nsexec die during
# "runc create" ("can't get final child's PID from pipe: EOF"). This wrapper
# rewrites the OCI config before delegating to the real runc:
#   * clamp negative process.oomScoreAdj to 0
#   * for containers sharing the host network namespace, replace the fresh
#     sysfs mount with a bind mount of the node's /sys (fresh sysfs mounts
#     can be refused when the host's /sys is partially masked)
set -euo pipefail

REAL_RUNC=/usr/local/sbin/runc

bundle=""
prev=""
for arg in "$@"; do
  if [[ "$prev" == "--bundle" || "$prev" == "-b" ]]; then
    bundle="$arg"
  fi
  prev="$arg"
done

if [[ -n "$bundle" && -f "$bundle/config.json" ]]; then
  python3 - "$bundle/config.json" <<'EOF' || true
import json
import sys

path = sys.argv[1]
with open(path) as f:
    spec = json.load(f)

changed = False

oom = spec.get("process", {}).get("oomScoreAdj")
if oom is not None and oom < 0:
    spec["process"]["oomScoreAdj"] = 0
    changed = True

namespaces = spec.get("linux", {}).get("namespaces", [])
has_own_netns = any(ns.get("type") == "network" for ns in namespaces)
if not has_own_netns:
    for m in spec.get("mounts", []):
        if m.get("destination") == "/sys" and m.get("type") == "sysfs":
            m["type"] = "bind"
            m["source"] = "/sys"
            m["options"] = ["rbind", "nosuid", "noexec", "nodev", "ro"]
            changed = True

if changed:
    with open(path, "w") as f:
        json.dump(spec, f)
EOF
fi

exec "$REAL_RUNC" "$@"
