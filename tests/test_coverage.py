"""다루는 지역 판별 — 규제 DB에 없는 국가는 "확인할 수 없음"으로 안내한다 (2026-10-21 화면에서 발견)."""
from app.domain.coverage import regions_in, unsupported_notice


def test_regions_in_separates_supported_and_unsupported():
    assert regions_in("P013 태국에 수출 가능해?") == ([], ["태국"])
    assert regions_in("P001 독일 수출 문제 있어?") == (["EU"], [])          # EU 회원국 → EU 규제로 확인
    assert regions_in("UK REACH 대상이야?") == ([], ["UK"])                 # 영국은 EU 목록으로 대신할 수 없음
    assert regions_in("인도네시아와 베트남") == ([], ["베트남", "인도네시아"])
    assert regions_in("제품을 인도하기 전에 확인") == ([], [])               # 국가가 아닌 "인도"
    assert regions_in("이번 주 미국 EPA 규제 변경") == (["US"], [])
    assert regions_in("최근 국내외 규제 변경") == ([], [])                  # "국내외"는 모두 — 특정 지역 아님


def test_notice_says_cannot_confirm_and_not_exportable():
    notice = unsupported_notice(["태국"])
    assert "확인할 수 없습니다" in notice and "수출 가능 여부를 뜻하지 않습니다" in notice


def test_regulation_names_imply_regions():
    assert regions_in("TSCA 트리클로로에틸렌 최근 규제 동향") == (["US"], [])
    assert regions_in("화관법 제한물질 변경") == (["KR"], [])
    assert regions_in("REACH SVHC 후보 목록 추가") == (["EU"], [])
    assert regions_in("K-REACH 등록 대상이야?") == (["KR"], [])           # 한국 화평법
