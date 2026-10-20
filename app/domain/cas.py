"""CAS 등록번호 검증.

CAS 번호는 `2~7자리-2자리-1자리` 형식이고, 마지막 한 자리는 앞 숫자로 계산하는 체크 디지트다.
    71-43-2 (벤젠): 앞 숫자 7143을 오른쪽부터 1, 2, 3, 4를 곱해 더한다
                    3×1 + 4×2 + 1×3 + 7×4 = 42 → 42 % 10 = 2 → 마지막 자리 2와 일치

규제 판정은 물질 이름이 아니라 CAS로 대조하므로, CAS 한 글자가 틀리면 판정 전체가 틀린다.
이 함수는 세 곳에서 쓴다.
- Step 1: 데이터 파일의 오타 검사
- Step 2 이후: LLM이 원문에서 뽑거나 번역한 CAS가 형식상 올바른지 검사
"""
import re

CAS_PATTERN = re.compile(r"^(\d{2,7})-(\d{2})-(\d)$")


def cas_check_digit(body: str) -> int:
    """하이픈을 뺀 앞부분 숫자로 체크 디지트를 계산한다."""
    return sum(int(d) * w for w, d in enumerate(reversed(body), start=1)) % 10


def is_valid_cas(cas: str) -> bool:
    m = CAS_PATTERN.match(cas.strip())
    if not m:
        return False
    body = m.group(1) + m.group(2)
    return cas_check_digit(body) == int(m.group(3))


def find_cas_numbers(text: str) -> list[str]:
    """문장에서 CAS 형식 문자열을 찾는다 (체크 디지트까지 맞는 것만)."""
    candidates = re.findall(r"(?<![\d-])\d{2,7}-\d{2}-\d(?![\d-])", text)
    return [c for c in dict.fromkeys(candidates) if is_valid_cas(c)]
