#!/usr/bin/env bash
# Revive the kind cluster after a host/daemon restart (sandboxed dev hosts).
#
# Handles the failure modes we've hit in practice:
#  - cgroup mounts (cpuset, named systemd hierarchy) missing after host restart
#  - docker daemon not running
#  - node containers coming back with permuted IPs: docker assigns 172.18.0.x
#    by start order, but each kubelet keeps reporting its original --node-ip,
#    which desyncs kindnet's node matching and poisons /etc/cni/net.d with the
#    wrong podCIDR. Fix: start node containers in ascending original-IP order.
#  - pods stuck with IPs outside their node's podCIDR from a poisoned CNI
#    config: recreate them.
set -euo pipefail

CLUSTER_NAME="k8s-sentinel"

echo "==> Ensuring cgroup mounts"
mkdir -p /sys/fs/cgroup/systemd /sys/fs/cgroup/cpuset
mountpoint -q /sys/fs/cgroup/systemd \
  || mount -t cgroup -o none,name=systemd cgroup /sys/fs/cgroup/systemd
mountpoint -q /sys/fs/cgroup/cpuset \
  || mount -t cgroup -o cpuset cgroup /sys/fs/cgroup/cpuset
echo 1 > /sys/fs/cgroup/cpuset/cgroup.clone_children

echo "==> Ensuring docker daemon"
if ! docker ps > /dev/null 2>&1; then
  dockerd > /tmp/dockerd.log 2>&1 &
  disown
  until docker ps > /dev/null 2>&1; do sleep 1; done
fi

NODES=$(docker ps -a --filter "label=io.x-k8s.kind.cluster=$CLUSTER_NAME" --format '{{.Names}}')
if [[ -z "$NODES" ]]; then
  echo "no kind nodes found for cluster $CLUSTER_NAME — run scripts/setup.sh instead"
  exit 1
fi

echo "==> Restarting node containers in original-IP order"
ORDERED=$(for n in $NODES; do
  ip=$(docker exec "$n" sh -c \
    "grep -o 'node-ip=[0-9.]*' /var/lib/kubelet/kubeadm-flags.env" 2>/dev/null \
    | cut -d= -f2 || true)
  # fall back to current address if the container isn't running yet
  [[ -n "$ip" ]] || ip=$(docker inspect "$n" \
    --format '{{.NetworkSettings.Networks.kind.IPAddress}}')
  echo "$ip $n"
done | sort -V | awk '{print $2}')
docker stop $NODES > /dev/null
for n in $ORDERED; do
  docker start "$n" > /dev/null
  sleep 1
done
docker ps --filter "label=io.x-k8s.kind.cluster=$CLUSTER_NAME" \
  --format '  {{.Names}} up'

echo "==> Waiting for the API server and node readiness"
until kubectl get nodes > /dev/null 2>&1; do sleep 3; done
until [[ "$(kubectl get nodes | grep -c ' Ready')" == "$(echo "$NODES" | wc -w)" ]]; do
  sleep 5
done

echo "==> Recreating pods whose IP is outside their node's podCIDR"
python3 - <<'EOF'
import ipaddress
import json
import subprocess

def get(args):
    return json.loads(subprocess.run(
        ["kubectl", *args, "-o", "json"], capture_output=True, text=True, check=True
    ).stdout)

cidrs = {n["metadata"]["name"]: ipaddress.ip_network(n["spec"]["podCIDR"])
         for n in get(["get", "nodes"])["items"]}
for p in get(["get", "pods", "-A"])["items"]:
    ip, node = p["status"].get("podIP"), p["spec"].get("nodeName")
    if not ip or not node or p["spec"].get("hostNetwork"):
        continue
    if ipaddress.ip_address(ip) not in cidrs[node]:
        ns, name = p["metadata"]["namespace"], p["metadata"]["name"]
        print(f"  recreating {ns}/{name} ({ip} not in {cidrs[node]})")
        subprocess.run(["kubectl", "-n", ns, "delete", "pod", name, "--wait=false"],
                       check=False)
EOF

echo "==> Waiting for all pods to be Running"
until [[ "$(kubectl get pods -A 2>/dev/null \
        | grep -cvE 'Running|Completed|NAMESPACE')" == "0" ]]; do sleep 5; done
kubectl get pods -A | grep -vE "Running|Completed" || true
echo "==> Cluster revived"
