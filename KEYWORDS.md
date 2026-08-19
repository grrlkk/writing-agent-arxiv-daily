# 토픽과 연구 축 매핑

이 트래커의 9개 토픽은 FEAK-TC(한국어 글쓰기 반복 수정을 transition 단위로 평가·제어하는
writing agent) 서론의 관련연구 축에서 그대로 따왔다. 각 토픽이 논문 어느 부분을 방어하는지 정리한다.

| 토픽 | FEAK-TC 대응 | 왜 추적하나 |
|---|---|---|
| Writing Agent | Z1 (기존 흐름), 서론 도입 | 반복 수정을 다루는 writing agent 패러다임 자체. 이 레포의 1순위 축 |
| Iterative Revision & Text Editing | B1 / W2 | edit intention taxonomy·revision history 선행연구. action taxonomy(ADD_DETAIL/COMPRESS/…)의 직접 비교 대상 |
| Self-Refine & Self-Correction | RQ4 baseline | "외부 검증 신호 없는 self-refine은 개선하지 못한다" — TVM 존재 이유의 논거 |
| Reward & Value Models | B2 / 2.2 | Bradley-Terry RM, process reward model, reward hacking. TVM이 속한 모델 계열 |
| Synthetic Preference Data | W3 (핵심 novelty) | corruption·perturbation·contrastive negative로 선호쌍을 만드는 선행. FEAK-guided corruption의 차별점을 세우려면 필수 |
| Text Quality Evaluation | Z2 | rubric 채점, LLM-as-a-judge, 자동 에세이 평가. FEAK 진단기의 자리 |
| Semantic Drift & Faithfulness | B3 | 수정 경로가 원문 의도에서 이탈했는지 감지 — global drift / rollback 신호 |
| Search & Control for Generation | B3 / W4 | tree search, verifier-guided decoding, stopping criterion. accept/reject/rollback/stop 제어층 |
| Korean Writing & NLP | 데이터·언어 | 한국어 에세이·채점·교정. 대상 언어 |

## 필터가 동작하는 방식

`config.yaml`의 각 토픽은 두 단계로 걸러진다.

- **`filters`** — 그 자체로 주제를 특정하는 구문(`"automated essay scoring"`, `"self-refine"`).
  토픽에 `anchors`가 있으면 그것까지 만족해야 한다.
- **`weak_filters`** — 일반적인 구문(`"corruption"`, `"rubric"`, `"tree search"`).
  `weak_anchors` 중 하나가 같이 나올 때만 채택된다.

arXiv API의 구문 검색이 느슨하기 때문에, 받아온 뒤 제목+초록에 그 구문이 실제로 들어 있는지
로컬에서 다시 확인한다. strong/weak는 **질의도 분리**한다 — 합치면 `"faithfulness"` 같은
고빈도 구문이 최신 N건을 다 차지해 정작 희귀한 `"semantic drift"` 논문이 밀려난다.

## 튜닝 순서

1. 노이즈가 한 부류로 몰려 들어오면 → 해당 토픽의 `weak_filters`/`weak_anchors`를 조정하거나
   `exclude_terms`에 도메인 어휘를 추가한다 (의료 영상, 음성, 코드 에이전트가 단골이다).
2. 개별 논문 한두 건만 문제면 → `blacklist.txt`에 arXiv id를 넣는다.
3. 특정 축을 넓히고 싶으면 → `filters`에 구문을 추가하고 `max_results`를 올린다.

## 학회 분류

학회 정보는 신뢰도 순으로 세 군데서 읽는다.

1. arXiv `journal_ref` 필드 — 저자가 게재 후 직접 채우는 값, 가장 확실하지만 드물다
2. **Semantic Scholar** 레코드 (`enrich.py`) — arXiv id로 조회, 키 없이 무료.
   결과는 `papers.json`에 캐싱하므로 한 번 조회한 논문은 다시 안 부른다
3. arXiv comment의 억셉 문구 — `"Accepted to ACL 2025"` 같은 자유 텍스트

`venues.yaml`을 고친 뒤 `python daily_arxiv.py --offline --no-enrich`를 돌리면
네트워크 호출 없이 전체가 다시 매겨진다.

판정은 세 가지를 따로 본다 (`venues.py`).

- **status** — `"Submitted to EACL 2026"`은 EACL 논문이 아니다. `"ACL style template"`도 아니다.
- **track** — `"ICLR 2026 Workshop"`은 ICLR 본회의가 아니다. Findings·demo도 별도 tier로 뺀다.
- **tier** — `venues.yaml`의 top/strong/other. 워크숍·Findings·demo는 학회 tier를 물려받지 못한다.

결과는 README 표의 Venue 열과 `docs/venues.md`에 나온다. 규칙 검증은 `python test_venues.py`.

**출처가 엇갈릴 때**: 학회명은 신뢰도 높은 출처를 따르되, 트랙은 세 출처를 모두 훑어
가장 구체적인 신호를 쓴다. Semantic Scholar는 Findings 논문을 모학회로 뭉뚱그려 기록하기
때문에(`"Accepted at ACL 2026 Findings"` → S2는 그냥 ACL), comment를 같이 보지 않으면
Findings 논문이 본회의로 둔갑한다. 실제로 11편이 그렇게 잘못 분류됐다가 고쳤다.

**커버리지 현실**: 751편 중 129편(17%)만 학회가 확인된다. 방법의 한계가 아니라 수집 대상의
성격이다 — 675편(90%)이 2026년 게시된 최신 프리프린트라 아직 학회에 실릴 시간이 없었다.
게시연도별 확인율은 2026년 15%, 2025년 40%, 2022년 67%로 오래될수록 올라간다.
`s2_recheck_days: 30`이 이걸 메운다. venue가 비어 있던 논문은 한 달 뒤 다시 조회하므로,
지금 프리프린트인 논문이 억셉되면 자동으로 채워진다.

**rate limit**: 키 없이 쓰면 429가 자주 뜬다. 6초 → 12초로 백오프하며 재시도하고,
한 번 실행에 최대 40요청(`s2_max_requests`)으로 끊는다. 실패해도 arXiv 메타데이터만으로
계속 진행하며 절대 실행을 깨뜨리지 않는다. 키가 있으면 `S2_API_KEY` 환경변수로 넣으면 된다.

## 로컬 실행

```bash
pip install -r requirements.txt

python daily_arxiv.py                          # 전체 토픽
python daily_arxiv.py --topics "Writing Agent" # 한 토픽만
python daily_arxiv.py --dry-run -v             # 몇 건이 통과하는지만 확인 (저장 안 함)
python daily_arxiv.py --offline                # 저장된 JSON으로 README·학회분류만 다시 생성
python test_venues.py                          # 학회 판정 규칙 테스트
```
