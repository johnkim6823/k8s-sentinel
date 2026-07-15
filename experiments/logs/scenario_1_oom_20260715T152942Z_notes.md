# Failure analysis — scenario_1_oom run 2026-07-15T15:29:42Z

The injection itself succeeded (pod OOMKilled at 15:29:43Z, exitCode 137,
restartCount 1), but the ContainerOOMKilled alert never fired within 10
minutes.

Root cause: the rule's recency guard was
`increase(kube_pod_container_status_restarts_total[15m]) > 0`. The injection
rolls out a lowered memory limit, which creates a **new pod**, and that pod
was OOM-killed 8 seconds after starting — before kube-state-metrics' first
scrape of it. The first sample of the new pod's restart counter was therefore
already 1, and with every sample in the window equal to 1, `increase()`
returns 0 (Prometheus does not assume a counter series started at 0), so the
guard never passed.

Fix (applied to deploy/monitoring/alert-rules.yaml): derive recency from
`kube_pod_container_status_last_terminated_timestamp` (time() - ts < 900)
instead of the restart-counter delta. The rerun at 15:42:12Z fired at
15:43:47Z (95 s after injection).
