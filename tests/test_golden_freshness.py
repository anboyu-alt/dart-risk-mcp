"""골드 출력이 **현재 코드가 내는 말**과 어긋나지 않는지 잠근다.

골드 263개는 `test_golden_output_hygiene`·`test_no_internal_key_leak`·
`test_no_severity_derived_stats`가 훑는 **검사 코퍼스**다(diff 기준이 아니다).
그래서 골드가 낡으면 **hygiene이 옛 출력을 훑는다** — 새로 들어간 문구는
한 번도 검사되지 않는다.

실측(2026-08-25): 골드 최종 재생성 이후 `dart_risk_mcp/`에 **19개 커밋**이
쌓였고, 골드에는 현재 코드가 더 이상 내지 않는 문구가 남아 있었다.

    「탐지 키워드」          17개 파일   ← #297이 「이 유형을 켜는 신호」로 바꿈
    「2개 이상 겹칩니다」     2개 파일   ← #295가 「표시 기준을 넘겨 겹칩니다」로 바꿈

이 파일은 **전량 일치를 요구하지 않는다**(골드는 라이브 API 산출물이라
회사 사정에 따라 매번 달라진다). 대신 **"코드가 버린 문구가 골드에 남아
있는가"**만 본다 — 남아 있으면 재생성이 밀린 것이다.

    python scripts/regen_goldens.py
"""
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_GOLD = _ROOT / "tests" / "fixtures" / "sample_outputs"

# (골드에 있으면 안 되는 문구, 그것을 걷어낸 근거)
_RETIRED = [
    ("### 탐지 키워드", "#297 — 도구가 검색하지 않는 말이라 「이 유형을 켜는 신호」로 바꿈"),
    ("2개 이상 겹칩니다", "#295 — 임계가 패턴 크기에 비례해 더는 2가 아니다"),
    ("위기 타임라인", "v0.8.5 — severity 파생 표기 제거"),
    ("12개월 내 3건 이상은 등록 패턴", "v1.20.10 — 희석성 기준으로 바뀜"),
    ("거래정지·상장폐지 관련·횡령 등 가장 무거운 유형입니다",
     "#277 — 카테고리 최악 사례를 나열하던 문구"),
]


def _texts():
    return {p.name: p.read_text(encoding="utf-8")
            for p in _GOLD.glob("*.txt")}


def test_골드가_존재한다():
    files = list(_GOLD.glob("*.txt"))
    assert len(files) > 100, f"골드가 {len(files)}개뿐이다"


@pytest.mark.parametrize("phrase,why", _RETIRED)
def test_걷어낸_문구가_골드에_없다(phrase, why):
    hits = sorted(n for n, t in _texts().items() if phrase in t)
    assert not hits, (
        f"골드 {len(hits)}개에 옛 문구가 남아 있다 ({why}).\n"
        f"  `python scripts/regen_goldens.py`로 재생성하세요.\n"
        f"  예: {hits[:5]}"
    )


def test_현재_코드가_그_문구를_실제로_내지_않는다():
    """반대 방향 확인 — 코드가 아직 내는데 골드만 지우면 이 테스트가 거짓이 된다.

    ⚠ **소스를 문자열 검색하면 안 된다.** 주석·docstring이 그 문구를 *인용*하기
    때문이다 — 이 파일도, `render._detecting_signals`도 옛 이름을 설명한다.
    처음에 소스를 훑도록 짰다가 그 자기참조로 실패했다. **출력**을 만들어 본다.
    """
    import sys

    sys.path.insert(0, str(_ROOT))
    from scripts.catalog.labels import load_labels
    from scripts.catalog.render import render_category

    from dart_risk_mcp.core.taxonomy import TAXONOMY

    md = render_category("Convertible Bond & Debt Manipulation", ["1.1"], {},
                         load_labels(), TAXONOMY, "2026-08-25")
    for phrase, why in _RETIRED:
        assert phrase not in md, f"카탈로그 렌더가 아직 '{phrase}'를 낸다 ({why})"


def test_서버_출력_경로에_죽은_렌더가_없다():
    """`timeline_text`는 `""`로 초기화된 뒤 **어디서도 대입되지 않았는데**
    「━━ 위기 타임라인 ━━」 렌더 블록이 남아 있었다(v0.8.5 제거의 잔재,
    2026-08-25 발견). 죽은 블록은 나중에 누군가 '고쳐서' 되살릴 수 있다."""
    src = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
    assert "timeline_text" not in src


def test_카탈로그_새_문구가_골드에_있다():
    """재생성이 실제로 새 렌더를 담았는지 — 한 방향만 보면 빈 골드도 통과한다."""
    texts = _texts()
    assert any("이 유형을 켜는 신호" in t for t in texts.values()), (
        "카탈로그 발췌를 담은 골드가 하나도 없다 — 재생성이 반영되지 않았다"
    )
