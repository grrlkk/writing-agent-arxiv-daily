# 토픽과 연구 축 매핑

이 트래커는 FEAK-TC(한국어 글쓰기 반복 수정을 transition 단위로 평가·제어하는
writing agent)의 관련연구와 다른 언어권으로의 에이전트 적용을 10개 토픽으로 추적한다.
각 토픽이 논문 어느 부분을 방어하는지 정리한다.

| 토픽 | FEAK-TC 대응 | 왜 추적하나 |
|---|---|---|
| Multilingual & Cross-Lingual Agents | 언어 간 전이·적용 근거 | 영어 중심 agent를 한국어·다른 언어권에 적용하는 방법, 다국어 도구 사용·계획·평가, 문화적 적응 |
| Writing Agent | Z1 (기존 흐름), 서론 도입 | 반복 수정을 다루는 writing agent 패러다임 자체. 이 레포의 1순위 축 |
| Iterative Revision & Text Editing | B1 / W2 | edit intention taxonomy·revision history 선행연구. action taxonomy(ADD_DETAIL/COMPRESS/…)의 직접 비교 대상 |
| Self-Refine & Self-Correction | RQ4 baseline | "외부 검증 신호 없는 self-refine은 개선하지 못한다" — TVM 존재 이유의 논거 |
| Reward & Value Models | B2 / 2.2 | Bradley-Terry RM, process reward model, reward hacking. TVM이 속한 모델 계열 |
| Synthetic Preference Data | W3 (핵심 novelty) | corruption·perturbation·contrastive negative로 선호쌍을 만드는 선행. FEAK-guided corruption의 차별점을 세우려면 필수 |
| Text Quality Evaluation | Z2 | rubric 채점, LLM-as-a-judge, 자동 에세이 평가. FEAK 진단기의 자리 |
| Semantic Drift & Faithfulness | B3 | 수정 경로가 원문 의도에서 이탈했는지 감지 — global drift / rollback 신호 |
| Search & Control for Generation | B3 / W4 | tree search, verifier-guided decoding, stopping criterion. accept/reject/rollback/stop 제어층 |
| Korean Writing & NLP | 데이터·언어 | 한국어 에세이·채점·교정. 대상 언어 |

## 검색 연도와 자동 수집

GitHub bot은 `config.yaml`의 `start_year: 2024`부터 실행 시점의 UTC 연도까지
**연도별로 따로 검색**한다. 2026년에는 2024·2025·2026년을 모두 조회하며, 다음 해에는
새 연도가 자동으로 포함된다. 기준은 학회 개최연도나 최신 수정일이 아니라 arXiv 최초 게시일이다.

이전에는 전체 기간에서 최신 N건만 조회해서 2026년 논문이 검색 상한을 거의 채웠다.
이제 `max_results`는 **토픽 × 연도 × strong/weak 질의**마다 독립적으로 적용된다.
기본값은 100건이고 일부 토픽은 150건이다. 이는 필터링 전 후보 수의 상한이며,
해당 연도의 모든 논문을 수집한다는 뜻은 아니다. 연도 구간은
[arXiv API의 submittedDate 필터](https://info.arxiv.org/help/api/user-manual.html#51-details-of-query-construction)를 사용한다.

README는 최신 20편을 보여주고, 각 토픽의 연도별 링크로 2024·2025년 목록에 바로
이동할 수 있다. 토픽별 아카이브는 연도별로 구분된다. 기존에 저장된 2024년 이전 논문도 유지한다.
수집 및 페이지 갱신은 기존 `.github/workflows/daily.yml` bot이 수행한다.

## 다국어·언어 간 에이전트 서베이

`Multilingual & Cross-Lingual Agents`는 글쓰기 외의 에이전트 작업도 포함한다.
다국어·언어 간 전이·비영어권·저자원 언어·문화적 적응 표현이나 개별 언어명을 찾되,
`agent`, `agentic`, 도구 사용·함수 호출, writing assistant 중 하나가 함께 있어야 한다.
이 조건을 arXiv 질의에도 넣어 일반 다국어 모델 논문이 검색 상한을 채우는 것을 줄인다.

수집된 논문은 다음 관점으로 읽는다.

- **적용 언어·문화**: 한국어 및 다른 언어권, 저자원 언어, 코드 스위칭, 문화적 적응.
- **에이전트 작업**: 계획, 도구 사용, 웹 작업, 다중 에이전트 협업, 글쓰기·수정.
- **전이 방법**: 프롬프트·벤치마크 번역, 현지화, 다국어 학습, 언어 간 지식 전이.
- **평가**: 영어 대비 성공률, 언어별 성능 격차, 현지 언어·문화에 맞춘 평가 기준.

이 토픽은 서베이 후보를 자동 수집하는 목록이며, 단순 언어 지원 언급과 실제 에이전트
적용·실험은 원문을 읽을 때 구분해야 한다. `Korean Writing & NLP`는 기존처럼
한국어 글쓰기·채점·교정 중심으로 유지한다.

## 필터가 동작하는 방식

`config.yaml`의 각 토픽은 두 단계로 걸러진다.

- **`filters`** — 그 자체로 주제를 특정하는 구문(`"automated essay scoring"`, `"self-refine"`).
  토픽에 `anchors`가 있으면 그것까지 만족해야 한다.
- **`weak_filters`** — 일반적인 구문(`"corruption"`, `"rubric"`, `"tree search"`).
  `weak_anchors` 중 하나가 같이 나올 때만 채택된다.
- **`required_terms`** — 설정된 경우 적어도 하나가 반드시 함께 나와야 한다.
  API 질의와 로컬 필터에 모두 적용된다. 새 다국어 토픽에서 에이전트 관련성을 확인한다.

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

**커버리지 현실**: 최신 프리프린트뿐 아니라 과거 논문도 학회 메타데이터가 비어 있을 수 있다.
현재 확인된 편수는 `docs/venues.md`에 표시된다. `s2_recheck_days: 30`에 따라
venue가 비어 있던 논문은 한 달 뒤 다시 조회하므로, 게재 정보가 추가되면 자동으로 채워진다.

**rate limit**: 키 없이 쓰면 429가 자주 뜬다. 6초 → 12초로 백오프하며 재시도하고,
한 번 실행에 최대 40요청(`s2_max_requests`)으로 끊는다. 실패해도 arXiv 메타데이터만으로
계속 진행하며 절대 실행을 깨뜨리지 않는다. 키가 있으면 `S2_API_KEY` 환경변수로 넣으면 된다.

## 파일 구성

- `README.md` — 토픽별 최근 20편. 상한이 있어 크기가 늘지 않는다
- `docs/archive.md` — 아카이브 인덱스
- `docs/topics/<토픽>.md` — 토픽별 전체 목록. 한 파일에 다 넣으면 GitHub이 렌더링을
  포기할 만큼 커져서 토픽 단위로 쪼갰다 (하루 약 9편 유입, 논문당 약 770B)
- `docs/venues.md` — 학회별 분류 결과
- `docs/papers.json` — 원본 저장소. 위 마크다운은 전부 이걸로 다시 그리는 산출물이다

## 로컬 실행

```bash
pip install -r requirements.txt

python daily_arxiv.py                          # 전체 토픽
python daily_arxiv.py --topics "Writing Agent" # 한 토픽만
python daily_arxiv.py --years 2024 2025        # 지정 연도만 수집 (기존 기록은 유지)
python daily_arxiv.py --topics "Multilingual & Cross-Lingual Agents"
python daily_arxiv.py --dry-run -v             # 몇 건이 통과하는지만 확인 (저장 안 함)
python daily_arxiv.py --offline --no-enrich    # 네트워크 없이 저장된 JSON으로 페이지 재생성
python -m unittest test_daily_arxiv.py          # 연도별 수집·필터·페이지 생성 테스트
python test_venues.py                          # 학회 판정 규칙 테스트
```
