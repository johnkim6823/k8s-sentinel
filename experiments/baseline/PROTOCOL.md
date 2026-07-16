# 수동 대응 MTTR 베이스라인 — 실험 프로토콜

에이전트(자동 진단·대응) 성능과 비교할 대조군으로, 사람이 kubectl로 직접
장애를 진단·복구하는 데 걸리는 MTTR을 측정한다. 모든 수치는 이 문서의 절차와
`experiments/baseline/results.jsonl`의 원시 기록으로 재현 가능해야 한다.

## MTTR 정의

`mttr_seconds = recovery_confirmed_at - injected_at`

- **injected_at**: chaos 스크립트가 기록한 주입 시각
  (`experiments/logs/scenario_*_<ts>.json`)
- **recovery_confirmed_at**: 사람 판단이 아니라 `measure.py done`의 자동 검증이
  통과한 시각 — 해당 시나리오의 Prometheus 알람이 resolved(부재)이고 대상
  Deployment가 완전 Ready인 것을 API로 확인한 순간
- 따라서 MTTR에는 알람 해소 반영 지연(KSM 스크레이프 + 룰 평가, 최대 약 1분)이
  포함된다. 에이전트 측정도 동일한 검증을 사용하므로 비교는 공정하다.

## 실험 구성

- 시나리오 1(OOMKilled), 2(CrashLoopBackOff), 3(ImagePullBackOff) × 3회 = 9회
- 학습 효과 통제를 위해 라운드마다 시나리오 순서를 라틴 방격으로 섞는다:

| 라운드 | 순서 |
|---|---|
| 1 | 1 → 2 → 3 |
| 2 | 2 → 3 → 1 |
| 3 | 3 → 1 → 2 |

## 사전 조건 (각 라운드 시작 전 확인)

1. kind 클러스터와 모니터링 스택 전체 Running
   (`kubectl -n monitoring get pods`)
2. Prometheus port-forward 열려 있음:
   `kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 9090:9090 &`
3. app-a/app-b 정상 (`kubectl get pods`), 시나리오 알람 3종 모두 부재
4. 직전 회차의 잔여 상태 없음: app-b의 limit/env/image가 매니페스트와 일치

## 회차 절차 (모든 회차 동일)

1. **주입**: `python chaos/scenario_<N>_*.py inject`
2. **알람 인지**: Prometheus UI(:9090/alerts)에서 해당 알람이 firing이 될
   때까지 대기 — 운영자는 알람을 보고 나서야 대응을 시작한다
   (원인 선验 지식이 있어도 알람 전에 조치하지 않는다)
3. **조사** (kubectl만 사용, chaos 스크립트 restore 사용 금지):
   - `kubectl get pods` / `kubectl describe pod <pod>`
   - `kubectl logs <pod> [--previous]`
   - `kubectl get events --sort-by=.lastTimestamp`
   - 필요시 `kubectl rollout history deployment/app-b`
4. **원인 판단 후 조치** (예시 — 실제 조치는 조사 결과에 따름):
   - OOMKilled → limit 상향: `kubectl set resources ...`
   - CrashLoopBackOff(잘못된 설정) → 롤백: `kubectl rollout undo ...` 또는 env 제거
   - ImagePullBackOff → 이미지 원복: `kubectl set image ...` 또는 롤백
5. **복구 기록**: `python experiments/baseline/measure.py done --scenario <N>`
   — 자동 검증(알람 resolved + Deployment Ready) 통과 시각이 기록됨.
   특이사항은 `--notes`로 남긴다 (예: 조치를 두 번 시도함)
6. **정리**: `python chaos/scenario_<N>_*.py restore` 실행
   (수동 조치가 이미 복구했으면 사실상 no-op이며, 주입 로그에 restored_at을
   기록해 로그를 닫는 역할). 다음 회차 전에 사전 조건 4를 재확인한다.

## 리허설

본 측정 9회 전에 시나리오 1로 전체 흐름을 1회 리허설한다. 리허설 기록은
`measure.py done --rehearsal`로 `rehearsal-results.jsonl`에 격리하며
`results.jsonl`(본 데이터)에는 포함하지 않는다.

## 한계 (결과 해석 시 반드시 함께 인용)

- **원인을 아는 운영자의 하한선**: 측정자는 시나리오 설계자로서 주입된 원인과
  복구 방법을 사전에 알고 있다. 실제 운영자의 진단 시간(가설 수립·탐색·오판)이
  빠져 있으므로, 이 수치는 수동 대응 MTTR의 **낙관적 하한선**이다. 에이전트가
  이 하한선과 대등하기만 해도 실전 대비 우위로 해석할 여지가 있다.
- 단일 운영자, 단일 환경(kind), 소표본(시나리오당 3회)이므로 통계적 일반화는
  제한적이다. 평균±표준편차만 보고하고 검정은 하지 않는다.
- 샌드박스 환경 특성상 회차 사이에 클러스터가 재시작되면 알람 노이즈가 생길 수
  있다. 사전 조건 확인으로 통제한다.
