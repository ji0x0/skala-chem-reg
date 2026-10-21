# Step 1 — 규제 데이터와 가상 제품 데이터

> **이후 변경**: 규제 데이터는 Day1 저녁에 공식 원본 대조로 바뀌었다: 13개·59행(`to_verify`) → **11종 9,351행 전부 `official`** (화평법 허가물질·미국 SNUR는 대조할 물질 목록이 없어 제외, 가상 제품 20개). 자세한 내용: [regulation-verification.md](../regulation-verification.md)

## 목표
에이전트가 판단할 재료를 만든다: 국내외 규제 목록, 회사 제품·원료(가상), 규제 용어집, 미국 관보 원문 스냅샷. LLM은 아직 없고, 데이터와 데이터 검증 코드만 있다.

## 만드는 파일

```
data/
├── regulations/
│   ├── sources.csv          규제 13개 메타 (지역, 판정 방식, 기본 기준 함량, 의무, 출처, 우선순위)
│   └── listings.csv         규제 × 물질 등재 59행 (CAS, 항목, 기준 함량, 조건, 검증 상태)
├── products/products.csv    가상 제품 12개 × 성분 91행 (형태, 수출 지역, CAS, 역할, 함량)
├── glossary.csv             규제 용어 28개 (영·중·일·한 → 한국어 표기)
└── feeds/federal_register_tsca.json   미국 관보 실제 응답 스냅샷
app/domain/cas.py            CAS 체크 디지트 검증, 문장에서 CAS 추출
app/core/config.py           데이터 경로 5개 추가
scripts/fetch_feed_snapshot.py   연방 관보 API → 스냅샷
scripts/build_reg_db.py      CSV 검증 → data/regulations.db (Git 제외)
tests/test_reg_data.py
```

## 데이터 설계 요점

- **대조는 이름이 아니라 CAS로**: 물질 이름은 언어마다 다르지만 CAS는 같다. CAS 한 글자 오타는 판정 전체를 틀리게 하므로 체크 디지트로 검증한다.
- **수출 지역과 제품 형태가 판정을 바꾼다**: EU로 안 파는 제품엔 EU 규제를 적용하지 않는다. SVHC 0.1 wt% 정보 제공 의무는 성형품(article) 기준이다.
- **주성분만이 아니라 전체 배합을 넣는다**: 제품당 5~9개 성분. 주원료 외에 가소제·안정제·촉매·안료 같은 첨가제, **잔류 단량체**(염화비닐 1 ppm 등), **제조 공정 불순물**(사염화탄소 5 ppm 등), **재활용 원료에서 섞여 든 불순물**(옛 프탈레이트·HBCDD)까지 `role` 열로 구분한다. 규제 리스크는 이런 미량 성분에서 자주 생긴다.
- **정답을 심은 제품** (Step 6 평가 정답으로 쓴다)

| 제품 | 심어 둔 상황 | 판정에서 확인할 점 |
| --- | --- | --- |
| P001 PVC 전선 피복 | DEHP 28%, 납 0.15%, 잔류 염화비닐 1 ppm | EU SVHC·XVII 초과 / 염화비닐은 국내 특별관리 등재지만 극미량 |
| P002 PVC 바닥재 | 주 가소제 DINP(목록 외) + 재활용 유래 DEHP 0.08%·DBP 0.03% | **개별로는 SVHC 0.1% 미만이지만 Entry 51은 4종 합계 0.11% → 초과** |
| P003 탈지 세정제 | TCE 94.5% + 불순물 PCE 0.8%·사염화탄소 5 ppm | 미국 TSCA 6조 3종 동시 / 불순물에 규칙이 적용되는지 확인 필요 / EU 미수출 |
| P004 에폭시 코팅제 | 잔류 BPA 0.3%, 잔류 에피클로로히드린 5 ppm | 혼합물이라 SVHC 성형품 의무 아님 / CLP 분류는 혼합물 기준 확인 |
| P005 우레탄 접착제 | 디클로로메탄 15%, 주석 촉매 0.05% | 국내 관리대상 + 중국 우선관리 |
| P006 난연 PP | 데클로란 플러스 12%, 재활용 유래 HBCDD 0.08% | EU SVHC 초과(데클로란) / **HBCDD는 SVHC 미만이지만 일본 화심법 1종** |
| P007 발수 코팅제 | PFOA 불순물 25 ppm | **함량이 낮아도** 일본 화심법 1종 → 기준이 함량이 아님 |
| P008 고무 호스 | MCCP 8%, DIBP 2% | SVHC 2종, Entry 51 |
| P009 페놀수지 | 잔류 페놀 0.8%, 포름알데히드 0.5% | Entry 77은 **방출량 기준 → 함량으로 판정 불가** |
| P010 수성 도료 | 잔류 아크릴레이트, 보존제 MIT | 13개 목록에 없음 → "해당 없음" (오탐 확인용) |
| P011 PET 필름 | UV-328 2.5%, 촉매 잔류 삼산화안티몬 0.02% | EU SVHC 초과 / 안티몬은 CLP 분류만 |
| P012 용제 블렌드 | 벤젠 불순물 0.2%, 노말헥산 5.8% | 국내 특별관리·관리대상 / EU 미수출이라 XVII 해당 없음 |

- **국내 규제의 적용 범위**: 국내 생산 사업장이므로 산업안전보건법·화학물질관리법은 수출 지역과 상관없이 적용 대상이다 (Step 2 판정 규칙에 반영).
- 규제와 무관한 일부 성분(아크릴 공중합체, 계면활성제 등)의 CAS는 형식만 맞춘 **예시 값**이다.
- **검증 상태**: 등재 데이터는 초안이며 모든 행이 `status=to_verify`다. 공식 원본으로 확인한 행만 `official`로 바꾼다. 서비스는 검증 전 데이터임을 화면에 표시한다.

## 따라 하기

```bash
uv add httpx
```

```bash
uv run python scripts/fetch_feed_snapshot.py
```

```bash
uv run python scripts/build_reg_db.py
```

## 확인

1) 관보 스냅샷 (실제 API, 실행일에 따라 결과가 다르다)

```
저장: federal_register_tsca.json — 최근 30일 EPA TSCA 문서 4건
  2026-10-15 [Rule] Significant New Use Rules on Certain Chemical Substances (24-5.5e); Correction
  2026-10-15 [Rule] Significant New Use Rules on Certain Chemical Substances (26-1)
  2026-10-14 [Proposed Rule] Trichloroethylene (TCE); Regulation Under the Toxic Substances Control Act (TSCA
  2026-10-06 [Notice] Certain New Chemicals or Significant New Uses; Statements of Findings-June 2026
```

2) DB 생성

```
생성: regulations.db
  규제 13개 · 등재 59행(물질 29종) · 제품 12개(원료 91행) · 용어 28개
  ⚠️ 공식 원본 확인 전(to_verify): 59행
```

3) 미량 성분(1 wt% 미만)이 규제 목록에 걸리는 경우

```bash
sqlite3 -header -column data/regulations.db "SELECT i.product_id, i.ingredient_name, i.role, i.wt_pct, group_concat(DISTINCT l.reg_id) FROM ingredients i JOIN listings l USING(cas) WHERE i.wt_pct < 1 GROUP BY i.product_id, i.cas;"
```

15건이 나온다 (예: P002 재활용 유래 DEHP 0.08%, P007 PFOA 0.0025%, P012 벤젠 0.2%).

3-1) 한 물질이 국내외 규제에 동시에 걸리는지

```bash
sqlite3 -header -column data/regulations.db "SELECT r.region, r.list_name, l.entry_ref FROM listings l JOIN regulations r USING(reg_id) WHERE l.cas='79-01-6';"
```

```
region  list_name                        entry_ref
KR      특별관리물질
US      제6조 위험관리 규칙 대상 물질    TCE rule
EU      고위험 우려물질(SVHC) 후보 목록
EU      부속서 VI 조화된 분류
```

4) ⚠️ 의도된 실패 — 데이터에 오타를 넣으면 DB를 만들지 않는다. `listings.csv`의 `71-43-2`를 `71-43-3`으로 바꾸고 `build_reg_db.py`를 실행하면 `CAS 오류 '71-43-3'`과 행 번호가 나온다. 확인 후 되돌린다.

5) 테스트

```bash
uv run pytest -q
```

```
15 passed
```

## 다음 단계
Step 2에서 이 DB와 관보 API를 MCP 서버로 노출하고, CAS 대조·함량 기준 판정 코어를 만든다.
