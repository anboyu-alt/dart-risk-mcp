"""검색 패널과 키 패널이 **함께** 보인다 — 갈아 끼우지 않는다.

옛 화면은 둘을 맞바꿨다. `showSearch`가 키 패널(`#setupPanel`)을 숨기고,
「키 변경」(`#resetKey`)이 검색 패널(`#searchPanel`)을 숨겼다. 공용 키가 생기기
전에는 그래도 됐다 — 키가 없으면 어차피 아무것도 못 했으니까.

v1.27 이후로는 **키 없이도 하루 몇 곳이 조회되므로** 그 맞바꿈이 함정이 됐다.
시크릿 창에서 공용 키로 잘 쓰던 사람이 「키 변경」을 눌러 보면 검색 패널이
사라지는데, 「저장하고 시작」 버튼은 40자 키를 요구하므로 **돌아올 길이 없다.**
제작자가 라이브에서 실제로 갇혔다:

    시크릿 창으로 열면 이렇게 나온다. 그런데 모르고 키 입력 창으로 넘어가면
    다시 키 없이 검색하는 창으로 돌아가지 않음.

고친 방향은 "돌아가는 길을 하나 더 놓는다"가 아니라 **애초에 나가지지 않게
한다**이다. 두 패널의 표시 조건을 서로 독립으로 두면 함정이 성립하지 않는다.

    검색 패널 — 자기 키가 있거나 릴레이가 공용 키를 갖고 있다
    키   패널 — 자기 키가 없다

공용 키가 있고 자기 키가 없는 상태(= 무료 조회 중)에서 **둘 다 보인다.**

라이브 확인(목 릴레이 + 헤드리스, `free_scans: 5`):

    A. 키 없음 + 공용 키   search True  · setup True   · DOM 순서 검색 → 키
    B. 키 저장 후          search True  · setup False
    C. 키 변경 후          search True  · setup True   ← 옛 코드는 여기서 False
"""
import pathlib
import re

_HTML = pathlib.Path(__file__).resolve().parents[1] / "docs" / "tool" / "index.html"
_SRC = _HTML.read_text(encoding="utf-8")


def _cut(name: str) -> str:
    """`function name(...) { ... }`를 중괄호 균형으로 잘라낸다."""
    m = re.search(r"^(?:async )?function " + re.escape(name) + r"\s*\(", _SRC, re.M)
    assert m, "함수를 찾지 못했다: " + name
    depth, started = 0, False
    for j in range(m.start(), len(_SRC)):
        if _SRC[j] == "{":
            depth += 1
            started = True
        elif _SRC[j] == "}":
            depth -= 1
            if started and depth == 0:
                return _SRC[m.start():j + 1]
    raise AssertionError("중괄호가 닫히지 않았다: " + name)


def _handler(elem_id: str) -> str:
    """`$("id").onclick = () => { ... }` 본문을 잘라낸다."""
    m = re.search(r'\$\("' + re.escape(elem_id) + r'"\)\.onclick\s*=\s*\(\)\s*=>\s*\{', _SRC)
    assert m, "핸들러를 찾지 못했다: " + elem_id
    depth = 0
    for j in range(m.end() - 1, len(_SRC)):
        if _SRC[j] == "{":
            depth += 1
        elif _SRC[j] == "}":
            depth -= 1
            if depth == 0:
                return _SRC[m.start():j + 1]
    raise AssertionError("중괄호가 닫히지 않았다: " + elem_id)


# ── ① 함정 자체가 없을 것 ────────────────────────────────────────────

def test_키_변경이_검색_패널을_숨기지_않는다():
    """제작자가 갇힌 그 자리. 여기서 검색 패널을 숨기면 함정이 되돌아온다."""
    body = _handler("resetKey")
    assert '$("searchPanel").classList.add("hidden")' not in body, (
        "「키 변경」이 검색 패널을 숨긴다 — 공용 키로 쓰던 사람이 갇힌다")
    assert "renderKeyPanel()" in body, (
        "키를 지운 뒤 두 패널을 다시 그리지 않는다")


def test_최근_스캔도_숨기지_않는다():
    """옛 코드는 `recentWrap`까지 숨겨 재조회 경로마저 사라졌다."""
    assert '$("recentWrap").classList.add("hidden")' not in _handler("resetKey")


def test_showSearch가_키_패널을_무조건_숨기지_않는다():
    """숨김 판단은 `renderKeyPanel` 한 곳에서만 한다(자기 키 유무로).

    `showSearch`가 옛날처럼 무조건 `add("hidden")`을 하면, 공용 키로 조회 중인
    사람에게 "더 보려면 어떻게 하나"가 화면에서 사라진다.
    """
    body = _cut("showSearch")
    assert '$("setupPanel").classList.add("hidden")' not in body
    assert "renderKeyPanel()" in body


# ── ② 표시 조건이 서로 독립일 것 ─────────────────────────────────────

def test_두_패널의_표시_조건이_서로_독립이다():
    body = _cut("renderKeyPanel")
    # 검색 패널 — 자기 키가 있거나 공용 키가 있으면 보인다
    assert re.search(
        r'\$\("searchPanel"\)\.classList\.toggle\("hidden",\s*!\(k\s*\|\|\s*SERVER_KEY\)\)',
        body), "검색 패널의 조건이 (자기 키 || 공용 키)가 아니다"
    # 키 패널 — 자기 키가 없으면 보인다. **공용 키 유무를 보지 않는다.**
    assert re.search(
        r'\$\("setupPanel"\)\.classList\.toggle\("hidden",\s*!!k\)', body), (
        "키 패널의 조건이 '자기 키 없음' 하나가 아니다 — 공용 키를 조건에 넣으면 "
        "무료 조회 중인 사람에게 발급 안내가 안 보인다")


def test_검색_패널이_키_패널보다_위에_있다():
    """둘이 함께 보이므로 **순서가 곧 무엇이 주된 행동인지**를 말한다.

    이 화면의 목적은 종목을 조회하는 것이고 키 입력은 그다음이다. 옛 DOM은
    맞바꿈이 전제라 키 패널이 위였다(한 번에 하나만 보였으니 순서가 없는
    것과 같았다).
    """
    assert _SRC.index('id="searchPanel"') < _SRC.index('id="setupPanel"'), (
        "키 패널이 검색 패널보다 먼저 나온다")


# ── ③ 발급 안내가 눈에 띌 것 ─────────────────────────────────────────

def _setup_panel() -> str:
    i = _SRC.index('id="setupPanel"')
    j = _SRC.index('<!-- 즐겨찾기 -->', i)
    return _SRC[i:j]


def test_발급_안내가_문단_속_링크가_아니라_따로_선_상자다():
    """제작자 요청: *"api키를 신청하는 방법도 더 눈에 띄게 만들어주고."*

    옛 화면은 설명 문단 한가운데의 링크 한 개였다 — 키가 없어 아무것도 못 하는
    사람에게 가장 중요한 줄인데 본문에 묻혀 있었다.
    """
    panel = _setup_panel()
    assert 'class="keyhow"' in panel, "발급 안내 상자가 없다"
    m = re.search(r'<a class="keybtn"[^>]*href="(https://opendart\.fss\.or\.kr[^"]*)"', panel)
    assert m, "발급처로 가는 버튼 링크가 없다"
    assert 'target="_blank"' in panel and 'rel="noopener"' in panel


def test_발급_안내가_절차와_조건을_말한다():
    """"어디로 가라"만으로는 부족하다 — 무엇이 필요하고 얼마나 걸리는지."""
    steps = _setup_panel()
    for token in ("회원가입", "40자리", "증빙서류", "20,000건"):
        assert token in steps, f"발급 안내에 '{token}'이 없다"


def test_keybtn_스타일이_실제로_있다():
    """클래스만 붙고 CSS가 없으면 '눈에 띄게'가 성립하지 않는다."""
    i, j = _SRC.find("<style>"), _SRC.find("</style>")
    css = re.sub(r"/\*.*?\*/", " ", _SRC[i:j], flags=re.S)
    assert re.search(r"\.keybtn\s*\{[^}]*background:\s*var\(--amber\)", css), (
        ".keybtn에 버튼 배경이 없다")
    assert ".keyhow {" in css


# ── ④ 화면이 제 동작과 같은 것을 말할 것 ─────────────────────────────

def test_면책_문구가_공용_키_조회를_숨기지_않는다():
    """옛 문구는 *"조회는 사용자의 API 키로 사용자가 시작하며"*였다.

    키 없이도 조회되는 지금은 참이 아니다 — 그때 쓰이는 것은 운영자 키다.
    이 레포가 거듭 걷어내 온 "화면이 제 동작과 다른 것을 말한다" 부류라,
    사실을 지우지 말고 **한 줄 더 적는다**.
    """
    i = _SRC.index('<p class="disclaimer">')
    disc = _SRC[i:_SRC.index("</p>", i)]
    assert "조회는 사용자의 API 키로 사용자가 시작하며" not in disc, (
        "면책 문구가 아직 '모든 조회가 사용자 키'라고 말한다")
    assert "운영자 키" in disc, "공용 키로 대신 조회한다는 사실이 면책에 없다"
    # 사용자 키를 저장하지 않는다는 사실은 지우지 않는다 — 신뢰의 근거다.
    assert "서버에 저장되지 않습니다" in disc


# ── ⑤ KRX 키는 DART 키 상태와 독립이다 (2026-09-23) ──────────────────
#
# 「공시 전후 시장 반응」 패널은 사용자 본인의 KRX Open API 키로만 동작한다
# (약관 제11조 — 운영자 키로 대신 조회할 수 없다). 이 키는 DART 키와
# 완전히 별개의 저장소·화면 요소를 쓴다 — DART 키를 넣거나 지워도 KRX
# 키 칸은 영향을 받지 않고, 그 반대도 마찬가지다.

def test_krx_키_패널이_DART_키_함수를_참조하지_않는다():
    """`renderKeyPanel`(DART 전용)이 KRX 패널을 건드리면 두 키가 얽힌다."""
    body = _cut("renderKeyPanel")
    assert "krx" not in body.lower(), (
        "renderKeyPanel이 KRX 키 관련 요소를 참조한다 — DART 키 상태가 "
        "KRX 키 칸의 표시를 바꿀 수 있게 된다")


def test_krx_키_패널_함수가_DART_키를_참조하지_않는다():
    """`renderKrxKeyPanel`이 `LS_KEY`/`SERVER_KEY`를 읽으면 독립이 우연이 된다."""
    body = _cut("renderKrxKeyPanel")
    assert "LS_KEY" not in body and "SERVER_KEY" not in body, (
        "renderKrxKeyPanel이 DART 키 상태를 읽는다 — 독립이 구조로 보장되지 않는다")


def test_krx_키_패널은_hidden_토글을_받지_않는다():
    """`#krxKeyPanel`에 `classList.toggle("hidden"` 호출이 있으면 어떤 조건에서든
    DART 키 상태(또는 다른 상태)에 따라 사라질 수 있다 — 이 패널은 항상 보인다."""
    assert 'krxKeyPanel").classList.toggle("hidden"' not in _SRC
    assert 'krxKeyPanel").classList.add("hidden"' not in _SRC


def test_krx_키_저장과_삭제가_DART_키를_건드리지_않는다():
    body_save = _handler("saveKrxKey")
    body_clear = _handler("clearKrxKey")
    for body, name in ((body_save, "saveKrxKey"), (body_clear, "clearKrxKey")):
        assert "LS_KEY" not in body, f"{name}이 DART 키 저장소를 건드린다"
        assert "renderKeyPanel()" not in body, f"{name}이 DART 키 화면을 다시 그린다"


def test_krx_키_칸이_문서에_있다():
    assert 'id="krxKeyPanel"' in _SRC
    assert 'id="krxKeyMask"' in _SRC
    assert 'id="krxKeyInput"' in _SRC
    assert 'href="https://openapi.krx.co.kr"' in _SRC
    assert "제11조" in _SRC


def test_키_패널_문구를_JS가_상황에_맞게_바꾼다():
    """같은 패널이 두 상황에 쓰인다 — 걸려 있는 것이 다르므로 문구도 다르다.

    공용 키가 없는 배포에서는 키가 곧 진입 조건이고(정적 문구), 있으면
    한도를 푸는 선택지다(JS가 갈아 끼운다).
    """
    body = _cut("renderKeyPanel")
    assert "if (!SERVER_KEY) return;" in body, (
        "공용 키가 없을 때 정적 문구를 그대로 두는 분기가 없다")
    assert "keyPanelLabel" in body and "keyPanelLead" in body
    # 무료 조회 수는 서버가 단일 출처다 — 뷰어에 숫자를 박지 않는다.
    assert "FREE_SCANS" in body, "키 패널 문구가 무료 조회 수를 박아 넣었다"
    panel = _setup_panel()
    assert "본인의 DART 인증키" in panel, "공용 키 없는 배포용 정적 문구가 사라졌다"


# ── KRX 키가 있으면 입력 칸을 접는다 (2026-09-23 제작자 제보) ───────────────
#
# 「키를 이미 넣었는데 빈 입력 칸이 그대로 떠서 헷갈린다」 — 저장된 키 한 줄과
# 「변경」「삭제」만 남기고 입력 칸은 키가 없거나 「변경」을 눌렀을 때만 연다.
# 패널 자체는 여전히 숨기지 않는다(위 `test_krx_키_패널은_hidden_토글을_받지_않는다`).

def test_krx_키_입력_칸은_별도_블록이고_변경_취소_버튼이_있다():
    assert 'id="krxKeyEdit"' in _SRC
    assert 'id="changeKrxKey"' in _SRC and 'id="cancelKrxKey"' in _SRC
    body = _cut("renderKrxKeyPanel")
    assert 'krxKeyEdit").classList.toggle("hidden"' in body
    # 패널 자체를 접는 코드는 여전히 없다
    assert 'krxKeyPanel").classList' not in body


def test_krx_키가_있으면_입력_칸이_접히고_변경을_누르면_열린다(tmp_path):
    import json, shutil, subprocess
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node 없음")
    body = _cut("renderKrxKeyPanel")
    js = """
const _store = {};
global.localStorage = { getItem: (k) => (k in _store ? _store[k] : null),
  setItem: (k, v) => { _store[k] = String(v); }, removeItem: (k) => { delete _store[k]; } };
const els = {};
const mk = () => ({ hidden: false, textContent: "", value: "", focus() {},
  classList: { toggle(c, on) { if (c === "hidden") this._el.hidden = !!on; } } });
for (const id of ["krxKeyMask", "krxKeyEdit", "changeKrxKey", "clearKrxKey", "cancelKrxKey", "krxKeyInput"]) {
  const e = mk(); e.classList._el = e; els[id] = e;
}
global.$ = (id) => els[id];
const LS_KRX_KEY = "dart_tool_krx_key";
let KRX_KEY_EDITING = false;
""" + body + """
const out = {};
renderKrxKeyPanel();                       // 키 없음
out.noKey = { edit: els.krxKeyEdit.hidden, change: els.changeKrxKey.hidden, clear: els.clearKrxKey.hidden, mask: els.krxKeyMask.textContent };
_store[LS_KRX_KEY] = "A".repeat(18) + "B".repeat(18) + "CDEF";
renderKrxKeyPanel();                       // 키 있음
out.withKey = { edit: els.krxKeyEdit.hidden, change: els.changeKrxKey.hidden, clear: els.clearKrxKey.hidden, mask: els.krxKeyMask.textContent };
KRX_KEY_EDITING = true; renderKrxKeyPanel();   // 「변경」
out.editing = { edit: els.krxKeyEdit.hidden, change: els.changeKrxKey.hidden, cancel: els.cancelKrxKey.hidden };
console.log(JSON.stringify(out));
"""
    f = tmp_path / "krxpanel.js"
    f.write_text(js, encoding="utf-8")
    r = subprocess.run([node, str(f)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr[:800]
    out = json.loads(r.stdout)
    # 키 없음: 입력 칸 열림 · 변경/삭제 숨김
    assert out["noKey"] == {"edit": False, "change": True, "clear": True, "mask": "(없음)"}
    # 키 있음: 입력 칸 접힘 · 변경/삭제 보임 · 가림표
    assert out["withKey"]["edit"] is True and out["withKey"]["change"] is False and out["withKey"]["clear"] is False
    assert out["withKey"]["mask"] == "AAAA…CDEF"
    # 변경: 입력 칸 열림 · 변경 버튼 숨김 · 취소 보임
    assert out["editing"] == {"edit": False, "change": True, "cancel": False}
