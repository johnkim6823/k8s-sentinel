# k8s-sentinel

LLM(Claude) 기반 Kubernetes 장애 자동 진단 및 대응 시스템(AIOps).

## 아키텍처

```
Alertmanager webhook
      ▼
[Sentinel Agent (FastAPI)]
  1. Context Collector   — Prometheus API, Loki API, K8s API (events/status/rollout history)
  2. Diagnosis Engine    — 구조화 프롬프트 → Claude API → JSON {root_cause, evidence[], confidence, recommended_action, action_safe_to_automate}
  3. Remediation Executor — 화이트리스트(restart/scale/rollback) + dry-run + 승인 게이트 + 실행 이력 DB
  4. Reporter            — Slack webhook
```

상세 계획은 [`docs/PLAN.md`](docs/PLAN.md), 개발 원칙은 [`CLAUDE.md`](CLAUDE.md) 참조.
