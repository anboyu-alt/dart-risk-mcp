"""CLAUDE.md 엔드포인트 표의 URL이 **코드에 실존하는지** 잠근다.

문서에 없는 URL을 적어 두면, 그걸 믿고 쓴 코드가 DART의 status 101
(「잘못된 URL입니다」)을 받는다. 실제로 두 번 나왔다.

    2026-08-25  채무증권 5종이 `…IsDecsn.json`(발행결정)으로 적혀 있었다
                → 실제는 `…NrdmpBlce.json`(미상환 잔액)
    2026-08-27  영업 양수가 `bsnAcqsDecsn.json`으로 적혀 있었다
                → 실제는 `bsnInhDecsn.json` (라이브 확인: 전자는 status 101,
                  후자는 000)

두 번 다 **코드는 처음부터 옳았고 문서만 틀렸다**. 그래서 코드를 보면
진실을 알 수 있는데, 문서를 먼저 본 사람은 없는 URL을 쓴다.

⚠ 표가 **모든** 엔드포인트를 담을 것을 요구하지는 않는다 — 48개를 손으로
유지하면 그게 다시 낡는다. 여기서 잠그는 것은 **적어 둔 것이 실존하는가**
한 방향뿐이다.
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_MD = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
_SRC = "\n".join(
    p.read_text(encoding="utf-8")
    for p in (_ROOT / "dart_risk_mcp").rglob("*.py")
)


def _table_endpoints() -> set:
    """표의 `GET /api/xxx.json`과 같은 칸의 `yyy.json` 짝을 모두 모은다."""
    eps = set(re.findall(r"GET /api/([A-Za-z][A-Za-z0-9]*)\.(?:json|xml)", _MD))
    for line in _MD.splitlines():
        if "GET /api/" not in line:
            continue
        eps |= set(re.findall(r"`([A-Za-z][A-Za-z0-9]*)\.(?:json|xml)`", line))
    return eps


def test_표에_적힌_엔드포인트가_코드에_있다():
    missing = sorted(e for e in _table_endpoints() if e not in _SRC)
    assert not missing, (
        "표에 적힌 URL을 코드가 부르지 않는다 — 오기이거나 죽은 문서다.\n"
        "DART에 직접 던져 status를 확인하고 고치세요: " + ", ".join(missing)
    )


def test_검사가_실제로_무언가를_본다():
    eps = _table_endpoints()
    assert len(eps) >= 30, f"표에서 {len(eps)}개만 찾았다 — 파싱이 헛돈다"


def test_과거_오기가_되살아나지_않는다():
    """⚠ **문서 전체를 검색하면 안 된다** — 정정 주석이 옛 이름을 *인용*한다.
    표의 `GET /api/…` 줄만 본다(이 함정에 이번 세션에서만 네 번째로 걸렸다).
    """
    rows = [l for l in _MD.splitlines() if "GET /api/" in l]
    body = "\n".join(rows)
    for wrong, why in [
        ("bsnAcqsDecsn", "영업 양수 — 실제는 bsnInhDecsn"),
        ("otcprStkInvscrAcqsDecsn", "타법인 주식 양수 — 실제는 otcprStkInvscrInhDecsn"),
        ("cprndIsDecsn", "회사채 — 실제는 cprndNrdmpBlce"),
    ]:
        assert wrong not in body, why
