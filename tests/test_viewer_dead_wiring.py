"""뷰어에서 **계산해 놓고 화면에 못 닿는 값**과 **조용한 절단**을 잠근다.

라벨 감사에서 나온 네 건(2026-08-30). 공통 유형은 앞선 라운드들과 같다 —
「라벨이 주장하는 것」과 「값이 실제로 하는 것」의 어긋남.

## 1. `equityRatio`가 추출되고 버려졌다

2026-08-28에 「core는 자기자본대비 12.4·17.3·6.8을 내는데 뷰어는 공란」이라며
`parseOutflowDetail`에 추출을 넣었다. 그런데 그 값이 `normalizeOutflowDetail`을
지나며 **키째로 사라졌고**, `assetTransferCardHTML`의

    if (d.equityRatio) extra.push(`자기자본 대비 …`)

는 **한 번도 참이 된 적이 없다.** 「누구에게 얼마가 나갔나」에서 규모 감각을
주는 유일한 값이라 공란이 아프다. 추출만 고치고 배선을 안 본 것이다.

## 2. 절단된 회사에서 「전체 공시」가 수집분을 가리켰다

2026-08-24에 KPI를 「수집 공시」로 고쳤는데 `renderProcedural`에는 그 수정이
안 닿았다. 삼성전자 1년(수집 1,000 · 전체 2,892)이면 한 화면에서

    KPI      수집 공시 1000
    주석     이 기간 전체 공시는 2892건
    절차 블록 대량보유상황보고 N건 — **전체 공시 1000건 중**

## 3. 세 블록이 조용히 잘렸다

`detailBlockHits`가 `maxCheck`에서 `break`해 **전체가 몇 건인지 세지 않았다.**
바로 옆 `loadCapitalBackflowGate`는 「N건 중 최근 M건만 확인 · P건 미확인」을
적는데 이쪽만 아무 말이 없었다. 상한은 그대로 두고(원문 ZIP 비용) 표기만 넣는다.

## 4. `elestock`를 「5% 대량보유」라 불렀다

`elestock`는 **임원·주요주주 특정증권 소유보고**이고 5% 대량보유는
`majorstock`가 따로 준다 — CLAUDE.md가 이 혼동을 경고하고 있고 core는
2026-08-28에 라벨을 정정했다. **뷰어만 옛 이름으로 남아** 다른 모집단을 그
이름으로 불렀다.
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
_SRV = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")


def _code() -> str:
    """주석을 뺀 코드만 — 근거 주석이 옛 식을 인용하고 있어 그대로 검사하면
    영원히 실패한다(실제로 한 번 걸렸다)."""
    body = re.sub(r"<!--.*?-->", "", _HTML, flags=re.S)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    keep = [l for l in body.splitlines() if not l.strip().startswith("//")]
    return chr(10).join(keep)


def _fn(name: str) -> str:
    i = _HTML.index(f"function {name}(")
    depth, j, in_s, q = 0, i, False, ""
    while j < len(_HTML):
        c = _HTML[j]
        if in_s:
            if c == "\\":
                j += 2
                continue
            if c == q:
                in_s = False
        elif c in "\"'`":
            in_s, q = True, c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return _HTML[i:j + 1]
        j += 1
    raise AssertionError(name)


# ── 1. 죽은 배선 ────────────────────────────────────────────────
def test_정규화가_equityRatio를_담는다():
    body = _fn("normalizeOutflowDetail")
    assert "equityRatio: (d && d.equityRatio) || \"\"" in body


def test_파서가_그_키를_실제로_낸다():
    """정규화만 고치고 파서가 안 내면 여전히 공란이다."""
    assert "return { counterparty, relation, amount, equityRatio };" in _HTML


def test_카드가_그_키를_읽는다():
    body = _fn("assetTransferCardHTML")
    assert "if (d.equityRatio)" in body
    assert "자기자본 대비" in body


def test_자산총액_대비와_섞지_않는다():
    """자산 처분은 자산총액 대비, 금전대여·담보는 자기자본 대비 — 분모가 다르다."""
    body = _fn("normalizeOutflowDetail")
    assert "assetRatio: 0" in body, "금전대여 서식에 자산총액 대비를 채우면 안 된다"
    card = _fn("assetTransferCardHTML")
    assert "자산총액 대비" in card and "자기자본 대비" in card


# ── 2. 절단 라벨 ────────────────────────────────────────────────
def test_절차_블록이_절단_여부에_따라_라벨을_바꾼다():
    body = _fn("renderProcedural")
    assert 'CUR.truncated ? "수집 공시" : "전체 공시"' in body
    assert "${denomLabel} ${totalCount}건 중" in body
    assert "— 전체 공시 ${totalCount}건 중" not in body, "옛 문구가 남아 있다"


def test_KPI도_같은_규칙을_쓴다():
    """두 곳이 갈리면 같은 화면에서 또 어긋난다."""
    i = _HTML.index('<div class="kpis">')
    assert 'CUR.truncated ? "수집 공시" : "전체 공시"' in _HTML[i:i + 900]


# ── 3. 조용한 절단 ──────────────────────────────────────────────
def test_전체_건수를_센다():
    body = _fn("detailBlockHits")
    assert "hits.total = total;" in body
    assert "if (hits.length >= maxCheck) break;" not in body, "옛 break가 남아 있다"
    assert "if (hits.length < maxCheck) hits.push(" in body


def test_생략이_없으면_아무_말도_하지_않는다():
    body = _fn("detailCapNote")
    assert "if (total <= shown) return \"\";" in body
    assert "미확인" in body


def test_세_블록이_모두_밝힌다():
    for card in ("relatedPartyCardHTML(rows)", "earningsShockCardHTML(rows)",
                 "assetTransferCardHTML(rows)"):
        assert f"detailCapNote(hits) + {card}" in _HTML, f"{card}에 표기가 없다"


def test_두_조회를_합칠_때_total도_합친다():
    """`concat`은 커스텀 속성을 옮기지 않는다 — 놓치면 total이 0이 된다."""
    body = _fn("loadAssetTransferCore")
    assert "hits.total = (atHits.total || 0) + (foHits.total || 0);" in body


def test_원문_조회_상한은_그대로다():
    """상한을 없앤 게 아니라 밝힌 것이다 — 비용이 늘면 안 된다."""
    body = _fn("loadAssetTransferCore")
    assert 'detailBlockHits("ASSET_TRANSFER", 4)' in body
    assert 'detailBlockHits("FUND_OUTFLOW", 4)' in body
    assert 'detailBlockHits("RELATED_PARTY", 3)' in _HTML
    assert 'detailBlockHits("EARNINGS_SHOCK", 2)' in _HTML


# ── 4. elestock 이름 ────────────────────────────────────────────
def test_elestock를_5퍼센트_대량보유라_부르지_않는다():
    for bad in ("▍5% HOLDINGS", "대량보유 보고 조회 중", "5% 대량보유 보고 이력이"):
        assert bad not in _HTML, f"옛 이름이 남아 있다: {bad}"


def test_실제_엔드포인트_이름으로_부른다():
    assert 'dartGet("elestock.json"' in _HTML, "대상 엔드포인트가 바뀌었다"
    assert "임원·주요주주 소유보고" in _HTML
    assert "임원·주요주주 특정증권 소유보고" in _HTML


def test_5퍼센트_대량보유가_아님을_밝힌다():
    i = _HTML.index("elestock)의 공개 기록 미러링")
    body = _HTML[i - 200:i + 400]
    assert "5% 대량보유 보고가 아닙니다" in body
    assert "majorstock" in body


def test_core와_같은_이름을_쓴다():
    """core는 2026-08-28에 정정했다 — 두 화면이 같은 것을 같은 이름으로 부른다."""
    assert '"elestock":      "임원·주요주주 소유보고"' in _SRV


def test_마크다운_굵게_표기가_렌더_문자열에_새지_않는다():
    """`**`는 HTML에서 그대로 찍힌다 — 이 수정에서 실제로 한 번 넣었다 뺐다."""
    # ⚠ 줄 단위로 `<!--`를 찾으면 **여러 줄 주석의 중간 줄**을 잡는다(처음에
    # 실제로 걸렸다). 주석 블록을 먼저 지우고 남은 것만 본다. 줄 번호를
    # 보존하려고 지운 자리를 개행으로 채운다.
    def _blank(m):
        return "\n" * m.group(0).count("\n")

    body = re.sub(r"<!--.*?-->", _blank, _HTML, flags=re.S)
    body = re.sub(r"/\*.*?\*/", _blank, body, flags=re.S)
    leaked = []
    for i, line in enumerate(body.splitlines(), 1):
        st = line.strip()
        if "**" not in line or st.startswith("//"):
            continue
        leaked.append(f"{i}: {st[:80]}")
    assert not leaked, "렌더 문자열에 마크다운 굵게 표기:\n  " + "\n  ".join(leaked)


def test_상한_표기_문구가_core의_결과_따른다():
    """core는 「N건 중 최근 M건의 원문만 확인 · P건 미확인」이라 적는다."""
    assert re.search(r"원문만 확인", _fn("detailCapNote"))
    assert "미확인" in _SRV


# ── 5. 사업연도도 KST ───────────────────────────────────────────
def test_사업연도가_KST다():
    """DART `bsns_year`는 KST 연도다. 로컬 연도를 쓰면 KST 1/1 00~09시에
    작년을, KST보다 앞선 시간대에선 12/31 저녁에 내년을 조회한다."""
    # ⚠ 근거 주석에도 옛 식이 인용돼 있다 — **코드만** 본다.
    assert "new Date().getFullYear()" not in _code(), "로컬 연도가 남아 있다"
    assert "function kstYear()" in _HTML
    assert "kstDate(Date.now()).getUTCFullYear()" in _HTML


def test_연도_사용처가_모두_헬퍼를_쓴다():
    """8곳을 한 번에 바꿨다 — 하나라도 남으면 그 화면만 축이 다르다."""
    assert _HTML.count("kstYear()") >= 9, "정의 + 사용처 8곳"


# ── 6. 기간 수 하드코딩(예방) ───────────────────────────────────
#
# ⚠ 이것은 **결함이 아니었다.** `기간`은 `RATIO_PERIODS`(현재 3)에서만 오므로
# 「3기간」은 지금 참이다. 회전율 블록에서 같은 하드코딩이 5년 선택 시 거짓이
# 되는 것을 이미 겪어(v1.21.0) 같은 함정을 미리 없앤 것이다.

def test_기간_수를_파생값으로_적는다():
    body = _fn("ratioTrendLine")
    assert "const _n = rows.length;" in body
    assert "${_n}기간 연속 상승" in body and "${_n}기간 연속 하락" in body
    assert "3기간 연속 상승" not in body


def test_경고_문구도_같은_값을_쓴다():
    assert "${debt.periods}기간 연속 상승" in _HTML
    assert "${current.periods}기간 연속 하락" in _HTML
    assert "periods: _n," in _HTML, "반환값에 안 실으면 경고 쪽이 undefined가 된다"


def test_지금은_3이_맞다():
    """파생으로 바꿨다고 값이 달라지면 안 된다 — 오늘의 출력은 동일해야 한다."""
    i = _HTML.index("const RATIO_PERIODS = [")
    block = _HTML[i:_HTML.index("];", i)]
    assert block.count("period:") == 3
