"""부실 이벤트 4종이 읽는 필드명을 **공식 명세와 대조**한다.

위험 목록 7번을 제작자 승인으로 처리한 결과(2026-08-30).

## 무엇이 문제였나

`_distress_summary`는 서브타입마다 필드를 읽고 **`or "기본 문자열"`로
떨어뜨린다**.

    cn = item.get("df_cn") or "부도"
    return item.get("ds_rs") or "해산사유 발생"

이 모양에서 이미 **실사고가 났다** — `rehabilitation`이 실존하지 않는
`rs`/`ctrcvs_rs`를 읽어, 신청사유가 응답에 있어도 **항상 하드코딩 문자열**만
나왔다(2026-08-04 발견, 실제 필드는 `rq_rs`). 폴백이 오류를 삼켜 몇 달간
아무도 몰랐다.

위험 목록은 「부도·해산은 발화 사례가 없어 검증할 수 없다」고 적고, 선택지로
「실제 사례를 찾아 검증(시간이 든다)」을 들었다.

## 라이브 사례 없이 검증됐다

**레포 안에 공식 명세가 있다** — `opendart_api_guide.md`. 거기서 네 엔드포인트의
고유 응답 필드를 그대로 읽어 코드와 대조하면 된다. 실제 부도·해산 회사를
찾을 필요가 없었다.

    dfOcr        df_cn · df_amt · df_bnk        ✓ 명세에 있다
    bsnSp        bsnsp_cn · bsnsp_rs            ✓
    ctrcvsBgrq   rq_rs                          ✓ (2026-08-04 수정분)
    dsRsOcr      ds_rs                          ✓

이 테스트가 그 대조를 **기계로** 수행한다 — 명세에 없는 필드를 읽기 시작하면
잡힌다. `rehabilitation` 사고가 재발할 수 없다.
"""
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_GUIDE = (_ROOT / "opendart_api_guide.md").read_text(encoding="utf-8")
_SRC = (_ROOT / "dart_risk_mcp" / "core" / "dart_client.py").read_text(encoding="utf-8")

# 서브타입 → (엔드포인트, 코드가 읽는 필드들)
SUBTYPES = {
    "default": ("dfOcr", ("df_cn", "df_amt", "df_bnk")),
    "business_susp": ("bsnSp", ("bsnsp_cn", "bsnsp_rs")),
    "rehabilitation": ("ctrcvsBgrq", ("rq_rs",)),
    "dissolution": ("dsRsOcr", ("ds_rs",)),
}


def _spec_fields(endpoint: str) -> set:
    """가이드에서 그 엔드포인트의 「고유 응답 필드」 표를 읽는다."""
    i = _GUIDE.index(f"{endpoint}.json")
    # 다음 구분선(---)까지가 그 절이다
    j = _GUIDE.find("\n---", i)
    block = _GUIDE[i:j if j > 0 else len(_GUIDE)]
    return set(re.findall(r"^\|\s*`([a-z0-9_]+)`\s*\|", block, re.M))


def _summary_body() -> str:
    i = _SRC.index("def _distress_summary(")
    return _SRC[i:_SRC.index("\ndef ", i + 10)]


def test_명세를_실제로_읽는다():
    """표를 못 읽으면 아래 대조가 전부 공허하게 통과한다."""
    for ep, _ in SUBTYPES.values():
        fields = _spec_fields(ep)
        assert len(fields) >= 3, f"{ep}: 명세 필드 {len(fields)}개 — 파싱이 헛돈다"


@pytest.mark.parametrize("subtype", sorted(SUBTYPES))
def test_읽는_필드가_명세에_있다(subtype):
    endpoint, used = SUBTYPES[subtype]
    spec = _spec_fields(endpoint)
    missing = [f for f in used if f not in spec]
    assert not missing, (
        f"{subtype}({endpoint})이 명세에 없는 필드를 읽는다: {missing}\n"
        f"  명세 필드: {sorted(spec)}\n"
        "  — `rehabilitation`의 rs/ctrcvs_rs 사고와 같은 모양이다."
    )


@pytest.mark.parametrize("subtype", sorted(SUBTYPES))
def test_코드가_그_필드를_실제로_읽는다(subtype):
    """대조 목록이 코드와 어긋나면 이 테스트가 엉뚱한 것을 지킨다."""
    _, used = SUBTYPES[subtype]
    body = _summary_body()
    for f in used:
        assert f'"{f}"' in body, f"{subtype}이 {f}를 더 이상 읽지 않는다"


def test_옛_사고_필드가_되살아나지_않았다():
    # ⚠ 근거 주석이 옛 필드명을 **이력으로 인용**한다 — 코드 줄만 본다.
    code = "\n".join(
        l for l in _summary_body().splitlines() if not l.strip().startswith("#"))
    for bad in ('"ctrcvs_rs"', 'item.get("rs")'):
        assert bad not in code, f"실존하지 않는 필드가 돌아왔다: {bad}"
    # 주석의 설명은 남긴다 — 사라지면 다음 사람이 같은 필드를 다시 쓴다
    assert "ctrcvs_rs" in _summary_body(), "사고 근거 주석이 사라졌다"


def test_명세에_있는데_안_읽는_필드를_기록해_둔다():
    """지금 안 읽는다는 사실 자체는 결함이 아니다 — 다만 알고 있어야 한다.

    실측(2026-08-30): `dfOcr`의 `df_rs`(부도사유 및 경위)와 `dfd`(최종부도일자),
    `bsnSp`의 `bsnspd`·`ft_ctp` 등은 명세에 있지만 요약에 쓰지 않는다.
    라이브 사례가 없어 **렌더를 검증할 수 없으므로 넣지 않았다** — 검증 못 한
    필드를 화면에 올리는 것이 이 프로젝트에서 반복된 사고다.
    """
    spec = _spec_fields("dfOcr")
    assert "df_rs" in spec and "dfd" in spec
    body = _summary_body()
    assert '"df_rs"' not in body, (
        "df_rs를 읽기 시작했다면 라이브 사례로 렌더를 확인하고 이 테스트를 고쳐라"
    )
