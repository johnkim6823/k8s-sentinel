CLAUDE.md — k8s-sentinel
프로젝트 개요
LLM 기반 Kubernetes 장애 자동 진단 및 대응 시스템 (AIOps). Prometheus 알람을 트리거로 → 컨텍스트 수집(Loki 로그, 메트릭, K8s 이벤트) → Claude API로 근본 원인 분석(RCA) → Slack 리포트 → 승인된 조치(재시작/스케일/롤백)를 안전장치와 함께 자동 실행한다.
상세 계획은 `docs/PLAN.md` 참조. 작업 지시가 모호하면 항상 PLAN.md의 해당 주차/섹션을 먼저 확인할 것.
아키텍처

```
Alertmanager webhook
      ▼
[Sentinel Agent (FastAPI)]
  1. Context Collector   — Prometheus API, Loki API, K8s API (events/status/rollout history)
  2. Diagnosis Engine    — 구조화 프롬프트 → Claude API → JSON {root_cause, evidence[], confidence, recommended_action, action_safe_to_automate}
  3. Remediation Executor — 화이트리스트(restart/scale/rollback) + dry-run + 승인 게이트 + 실행 이력 DB
  4. Reporter            — Slack webhook

```

레포 구조

```
agent/
  main.py              # FastAPI 엔트리, Alertmanager webhook 수신
  collector/           # Prometheus/Loki/K8s 컨텍스트 수집
  diagnosis/           # 프롬프트, LLM 호출, 출력 검증
  remediation/         # 조치 실행기, 안전장치
  reporter/            # Slack 리포트
  storage/             # 실행 이력 (SQLite)
deploy/
  sample-apps/         # 대상 마이크로서비스 매니페스트
  monitoring/          # Prometheus 룰, Alertmanager 설정
  agent/               # 에이전트 배포 매니페스트
chaos/                 # 장애 주입 스크립트 (시나리오별, 원상복구 포함)
experiments/           # 실험 스크립트, 원시 로그, 분석
tests/
docs/                  # PLAN.md, 아키텍처 문서, 설계 결정 기록(ADR)
.github/workflows/     # CI (ruff, pytest, docker build)

```

코드 원칙

* 쉽고 간결하게. 표준 라이브러리 우선. 불필요한 프레임워크·추상화·디자인 패턴 금지
* 모듈은 단일 책임, 함수는 짧게. 한 파일이 200줄 넘으면 분리 검토
* 타입 힌트 필수. 외부 입출력 데이터는 pydantic 모델로 검증
* 모든 기능은 pytest 단위 테스트 포함. 구현만 하고 끝내지 말 것
* 의존성 추가는 최소화하고, 추가 시 이유를 커밋 메시지에 남길 것
* 시크릿(API 키, Slack webhook URL)은 환경변수로만. 코드/커밋에 절대 포함 금지
실험 원칙 (연구 방법론)

* 모든 정량 수치(진단 정확도, MTTR, 복구 성공률)는 `experiments/` 아래 원시 로그로 재현 가능해야 함
* 실험은 시나리오 × 반복 횟수를 사전에 명시하고, 실행 시각·파라미터·결과를 JSON으로 기록
* 대조군(수동 대응 baseline) 대비 비교로 보고. 단일 실행 수치를 결과로 쓰지 않음
* 실패 케이스는 삭제하지 말고 원인 분석과 함께 보존
장애 시나리오 6종 (chaos/)

1. OOMKilled — 메모리 limit 축소 + 부하 주입 → limit 상향 제안 + 재시작
2. CrashLoopBackOff — 잘못된 설정 배포 → 롤백
3. ImagePullBackOff — 존재하지 않는 이미지 태그 → 롤백
4. CPU throttling — CPU 부하 주입 → 스케일 아웃
5. Node DiskPressure — 대용량 파일 생성 → 알림만 (자동조치 제외)
6. 다운스트림 장애 — 의존 서비스 중단 → 알림만. 오진 방지 핵심 테스트: 앱 재시작으로 해결 안 되는 장애를 구분해야 함
안전 규칙 (Remediation)

* 조치는 화이트리스트만: `restart_pod`, `scale_deployment`, `rollback_deployment`
* 실행 전 반드시 dry-run 출력 → 승인 게이트 통과 → 실행 → N분 후 알람 해소 검증
* 시나리오 5, 6은 자동조치 대상 아님 (설계상 제외)
* 모든 실행은 storage에 이력 기록 (알람, 조치, 결과, 시각)
커밋 규칙

* 작은 단위로 자주 커밋
* Conventional commits: `feat:`, `fix:`, `test:`, `docs:`, `chore:`
* 커밋 전 ruff + pytest 통과 확인
