#!/usr/bin/env bash
# Install the monitoring stack into the current kubectl context:
#   - kube-prometheus-stack (Prometheus + Alertmanager + Grafana + kube-state-metrics)
#   - Loki (single binary) + Promtail
#   - the k8s-sentinel PrometheusRule (6 chaos scenarios) and app ServiceMonitor
#
# Env overrides for restricted networks:
#   KPS_CHART / LOKI_CHART / PROMTAIL_CHART — local chart directories to install
#     from instead of the public Helm repos (e.g. when *.github.io is blocked)
#   USE_REGISTRY_MIRROR=1 — additionally apply deploy/monitoring/mirrors/*.yaml
#     to pull images via mirror.gcr.io / Docker Hub mirrors
#   KIND_PRELOAD=1 — docker-pull the mirror images on the host and load them
#     into the kind cluster (for hosts whose proxy is unreachable from inside
#     the kind nodes). Implies the mirror image names; use with
#     USE_REGISTRY_MIRROR=1.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MON_DIR="$ROOT_DIR/deploy/monitoring"
NS=monitoring

KPS_VERSION="87.5.1"
LOKI_VERSION="18.3.1"
PROMTAIL_VERSION="6.17.1"

install_chart() {
  local release=$1 chart_override=$2 chart_name=$3 repo=$4 version=$5
  shift 5
  if [[ -n "$chart_override" ]]; then
    helm upgrade --install "$release" "$chart_override" -n "$NS" --create-namespace "$@"
  else
    helm upgrade --install "$release" "$chart_name" --repo "$repo" --version "$version" \
      -n "$NS" --create-namespace "$@"
  fi
}

MIRROR_KPS=() MIRROR_LOKI=() MIRROR_PROMTAIL=()
if [[ "${USE_REGISTRY_MIRROR:-0}" == "1" ]]; then
  MIRROR_KPS=(-f "$MON_DIR/mirrors/values-kps-mirror.yaml")
  MIRROR_LOKI=(-f "$MON_DIR/mirrors/values-loki-mirror.yaml")
  MIRROR_PROMTAIL=(-f "$MON_DIR/mirrors/values-promtail-mirror.yaml")
fi

# Keep this list in sync with the tags pinned in deploy/monitoring/mirrors/*.yaml
MIRROR_IMAGES=(
  mirror.gcr.io/rancher/mirrored-prometheus-operator-prometheus-operator:v0.87.1
  mirror.gcr.io/rancher/mirrored-prometheus-operator-prometheus-config-reloader:v0.87.1
  mirror.gcr.io/prom/prometheus:v3.13.0
  mirror.gcr.io/prom/alertmanager:v0.33.0
  mirror.gcr.io/grafana/grafana:13.1.0
  mirror.gcr.io/kiwigrid/k8s-sidecar:2.8.1
  mirror.gcr.io/rancher/mirrored-kube-state-metrics-kube-state-metrics:v2.15.0
  mirror.gcr.io/prom/node-exporter:v1.11.1
  mirror.gcr.io/grafana/loki:3.7.3
  mirror.gcr.io/grafana/promtail:3.5.1
)

if [[ "${KIND_PRELOAD:-0}" == "1" ]]; then
  echo "==> Preloading mirror images into kind cluster k8s-sentinel"
  for img in "${MIRROR_IMAGES[@]}"; do docker pull -q "$img"; done
  ARCHIVE=$(mktemp --suffix=.tar)
  # single-platform archive: ctr on the nodes can't import the multi-platform
  # manifests that docker save emits under the containerd image store
  docker save --platform linux/amd64 -o "$ARCHIVE" "${MIRROR_IMAGES[@]}"
  kind load image-archive "$ARCHIVE" --name k8s-sentinel
  rm -f "$ARCHIVE"
fi

echo "==> Installing kube-prometheus-stack"
install_chart monitoring "${KPS_CHART:-}" kube-prometheus-stack \
  https://prometheus-community.github.io/helm-charts "$KPS_VERSION" \
  -f "$MON_DIR/values-kube-prometheus-stack.yaml" "${MIRROR_KPS[@]}" --timeout 10m

echo "==> Installing Loki"
install_chart loki "${LOKI_CHART:-}" loki \
  https://grafana-community.github.io/helm-charts "$LOKI_VERSION" \
  -f "$MON_DIR/values-loki.yaml" "${MIRROR_LOKI[@]}" --timeout 10m

echo "==> Installing Promtail"
install_chart promtail "${PROMTAIL_CHART:-}" promtail \
  https://grafana.github.io/helm-charts "$PROMTAIL_VERSION" \
  -f "$MON_DIR/values-promtail.yaml" "${MIRROR_PROMTAIL[@]}" --timeout 10m

echo "==> Applying k8s-sentinel alert rules and app ServiceMonitor"
kubectl apply -f "$MON_DIR/alert-rules.yaml"
kubectl apply -f "$MON_DIR/app-servicemonitors.yaml"

echo "==> Waiting for the stack to come up"
kubectl -n "$NS" rollout status deployment/monitoring-kube-prometheus-operator --timeout=300s
kubectl -n "$NS" wait --for=condition=Ready pod -l app.kubernetes.io/name=prometheus --timeout=300s
kubectl -n "$NS" wait --for=condition=Ready pod -l app.kubernetes.io/name=alertmanager --timeout=300s
kubectl -n "$NS" get pods

cat <<'EOF'
==> Done. Handy commands:
  kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 9090:9090   # Prometheus UI
  kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-alertmanager 9093:9093 # Alertmanager UI
  kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80                        # Grafana UI
EOF
