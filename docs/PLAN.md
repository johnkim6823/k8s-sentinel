# PLAN — k8s-sentinel

LLM 기반 Kubernetes 장애 자동 진단 및 대응 시스템을 8주 동안 단계적으로 구축한다.
각 주차는 이전 주차의 산출물 위에 쌓는다. 세부 설계가 바뀌면 이 문서를 갱신하고,
큰 방향 결정은 `docs/adr/`에 근거를 남긴다.

## Week 1 — 프로젝트 뼈대 & 샘플 앱 & kind 클러스터

- CLAUDE.md의 레포 구조대로 디렉토리 생성, `pyproject.toml`(Python 3.11+, ruff, pytest),
  `.gitignore`, `LICENSE`(MIT), `README.md` 뼈대, `.env.example`
- `deploy/sample-apps/`에 대상 마이크로서비스 2개 (app-a → app-b 의존 관계)
  - FastAPI, Dockerfile, 리소스 requests/limits 명시한 K8s 매니페스트
  - chaos 주입용 디버그 엔드포인트: `/debug/memory`, `/debug/cpu`
- `deploy/kind-config.yaml` (멀티노드) + `scripts/setup.sh`
  (클러스터 생성 → 이미지 빌드/로드 → 배포 → app-a→app-b 호출 검증까지 원샷)
- 완료 조건: kind 클러스터에서 app-a → app-b 호출 성공, 디버그 엔드포인트 동작 확인

## Week 2 — 관측 스택

- Prometheus, Loki(+ promtail), Grafana를 `deploy/monitoring/`에 구성
- app-a/app-b에 대한 기본 알람 룰 (OOMKilled, CrashLoopBackOff, CPU throttling 등)
- Alertmanager → webhook 라우팅 확인 (수신 측은 Week 3에서 구현)

## Week 3 — Sentinel Agent 골격 & Context Collector

- `agent/main.py`: FastAPI, Alertmanager webhook 수신 (pydantic으로 payload 검증)
- `agent/collector/`: Prometheus API, Loki API, K8s API(events/status/rollout history) 수집기
- 단위 테스트: 각 수집기는 목(mock) 응답으로 검증

## Week 4 — Diagnosis Engine

- `agent/diagnosis/`: 구조화 프롬프트 설계, Claude API 호출, 출력 스키마
  `{root_cause, evidence[], confidence, recommended_action, action_safe_to_automate}` 검증
- 프롬프트/파서 단위 테스트 (LLM 호출은 목으로 대체)

## Week 5 — Remediation Executor & Reporter

- `agent/remediation/`: 화이트리스트(`restart_pod`, `scale_deployment`, `rollback_deployment`),
  dry-run, 승인 게이트, 실행 이력(`agent/storage/`, SQLite)
- `agent/reporter/`: Slack webhook 리포트
- 안전 규칙 전체 구현 및 테스트 (승인 없이는 실행 불가 등)

## Week 6 — Chaos 시나리오 6종

- `chaos/`에 시나리오별 주입 스크립트(원상복구 포함): OOMKilled, CrashLoopBackOff,
  ImagePullBackOff, CPU throttling, Node DiskPressure(알림만), 다운스트림 장애(알림만)
- 각 시나리오에 대해 에이전트 파이프라인 전체(알람→진단→리포트→[조치]) 수동 검증

## Week 7 — 실험 & 정량 평가

- `experiments/`: 시나리오 × 반복 횟수 사전 설계, 실행 시각/파라미터/결과 JSON 기록
- 수동 대응 baseline 대비 진단 정확도, MTTR, 복구 성공률 비교
- 실패 케이스 보존 및 원인 분석

## Week 8 — 정리 & 문서화

- README/아키텍처 문서 보강, ADR 정리, CI(`ruff`, `pytest`, `docker build`) 강화
- 남은 기술 부채 정리

## 참고

- 상세 원칙(코드/실험/안전/커밋)은 `CLAUDE.md` 참조
- 장애 시나리오 및 안전 규칙 세부 정의는 `CLAUDE.md`의 해당 섹션이 단일 소스
