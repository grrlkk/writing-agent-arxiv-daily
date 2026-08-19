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

각 논문의 학회는 arXiv 자체 메타데이터에서만 읽는다 — `journal_ref` 필드와, 저자가 comment에
적어두는 억셉 문구("Accepted to ACL 2025"). 외부 API를 쓰지 않으므로 재분류가 공짜고,
`venues.yaml`을 고친 뒤 `python daily_arxiv.py --offline`만 돌리면 전체가 다시 매겨진다.

판정은 세 가지를 따로 본다 (`venues.py`).

- **status** — `"Submitted to EACL 2026"`은 EACL 논문이 아니다. `"ACL style template"`도 아니다.
- **track** — `"ICLR 2026 Workshop"`은 ICLR 본회의가 아니다. Findings·demo도 별도 tier로 뺀다.
- **tier** — `venues.yaml`의 top/strong/other. 워크숍·Findings·demo는 학회 tier를 물려받지 못한다.

결과는 README 표의 Venue 열과 `docs/venues.md`에 나온다. 규칙 검증은 `python test_venues.py`.

**한계**: 저자가 comment에 안 적으면 알 수 없다. 현재 751편 중 약 110편(15%)만 근거가 있고,
나머지는 "미게재"가 아니라 "arXiv 메타데이터에 정보 없음"이다. 커버리지를 올리려면
Semantic Scholar나 DBLP API로 보강해야 하는데, 그건 네트워크 호출과 rate limit이 붙는다.

## 로컬 실행

```bash
pip install -r requirements.txt

python daily_arxiv.py                          # 전체 토픽
python daily_arxiv.py --topics "Writing Agent" # 한 토픽만
python daily_arxiv.py --dry-run -v             # 몇 건이 통과하는지만 확인 (저장 안 함)
python daily_arxiv.py --offline                # 저장된 JSON으로 README·학회분류만 다시 생성
python test_venues.py                          # 학회 판정 규칙 테스트
```
