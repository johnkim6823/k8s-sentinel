#!/usr/bin/env bash
# Create a local kind cluster, build+load the sample app images, deploy them,
# and verify app-a can reach app-b end to end.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="k8s-sentinel"
APPS_DIR="$ROOT_DIR/deploy/sample-apps"

# KIND_NODE_IMAGE / DOCKER_BASE_IMAGE let you override the node/base images with a
# mirror (e.g. in networks that block Docker Hub's CDN). Leave unset for defaults.
KIND_IMAGE_ARGS=()
if [[ -n "${KIND_NODE_IMAGE:-}" ]]; then
  KIND_IMAGE_ARGS=(--image "$KIND_NODE_IMAGE")
fi
BUILD_ARGS=()
if [[ -n "${DOCKER_BASE_IMAGE:-}" ]]; then
  BUILD_ARGS=(--build-arg "BASE_IMAGE=$DOCKER_BASE_IMAGE")
fi

echo "==> Creating kind cluster (if not present)"
if ! kind get clusters | grep -qx "$CLUSTER_NAME"; then
  # docker bind mounts need absolute host paths, so resolve __REPO_ROOT__ here
  RESOLVED_CONFIG=$(mktemp)
  sed "s|__REPO_ROOT__|$ROOT_DIR|g" "$ROOT_DIR/deploy/kind-config.yaml" > "$RESOLVED_CONFIG"
  kind create cluster --config "$RESOLVED_CONFIG" "${KIND_IMAGE_ARGS[@]}"
  rm -f "$RESOLVED_CONFIG"
else
  echo "cluster '$CLUSTER_NAME' already exists, reusing"
fi

echo "==> Building app images"
docker build "${BUILD_ARGS[@]}" -t app-a:dev "$APPS_DIR/app-a"
docker build "${BUILD_ARGS[@]}" -t app-b:dev "$APPS_DIR/app-b"

echo "==> Loading images into kind"
kind load docker-image app-a:dev --name "$CLUSTER_NAME"
kind load docker-image app-b:dev --name "$CLUSTER_NAME"

echo "==> Applying manifests"
kubectl apply -f "$APPS_DIR/app-b/k8s/deployment.yaml"
kubectl apply -f "$APPS_DIR/app-a/k8s/deployment.yaml"

echo "==> Waiting for rollouts"
kubectl rollout status deployment/app-b --timeout=120s
kubectl rollout status deployment/app-a --timeout=120s

echo "==> Verifying app-a -> app-b call via in-cluster exec"
POD=$(kubectl get pod -l app=app-a -o jsonpath='{.items[0].metadata.name}')
RESULT=$(kubectl exec "$POD" -- python3 -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/call-b/1').read().decode())")
echo "$RESULT"

if echo "$RESULT" | grep -q '"app_b_data"'; then
  echo "==> SUCCESS: app-a successfully called app-b"
else
  echo "==> FAILURE: unexpected response from app-a"
  exit 1
fi
