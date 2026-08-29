"""뷰어의 KST 날짜·시각이 **어느 시간대에서도** 맞는지 잠근다.

화면 머리글이 「T-1Y SCAN · 2026.08.29」인데 그날은 8월 30일이었다(2026-08-30
04:11 KST). 거기서 찾았다.

    function todayKST() {
      const d = new Date(Date.now() + (9 * 60 + new Date().getTimezoneOffset()) * 60000);
      return d.toISOString().slice(0, 10);
    }

`getTimezoneOffset()`은 「UTC − 로컬」을 분으로 주므로 한국에서 **-540**이다.
그러면 `9 * 60 + (-540) = 0` — 즉 한국 사용자에게는 **UTC를 그대로** 돌려줬다.
`toISOString()`이 이미 UTC로 렌더하니 로컬 오프셋을 더할 이유가 애초에 없었고,
이 식은 **UTC 브라우저에서만 우연히** 맞았다.

같은 식이 **세 곳**에 있었다.

    todayKST()   2026-08-29         하루 밀림 — 스캔 diff의 「N일 전」이 어긋난다
    시계          2026-08-29 19:11   「SESSION · KST」라 적어 놓고 9시간 어긋남
    ymd()        20260829           `end_de`가 어제 → **그날 오전 공시를 통째로 누락**

세 번째가 가장 무겁다. KST 00~09시에 스캔하면 조회 창이 하루 뒤로 밀리는데,
DART 접수는 07시대부터 시작한다 — 실제로 비어 있는 구간이다.

수정은 로컬 오프셋을 빼는 것뿐이다: `new Date(t + 9h).toISOString()`은 t의
**KST 벽시계**를 그대로 렌더한다(브라우저 시간대 무관).

⚠ core는 건드리지 않았다. 파이썬 쪽은 `datetime.now()`(기기 로컬)를 쓰는데,
MCP는 사용자 기기에서 도는 것이 전제라 한국 사용자에게는 KST가 맞다. 서버로
옮긴다면 그때 별도로 볼 문제다.
"""
import datetime
import json
import os
import pathlib
import shutil
import subprocess
import tempfile

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node가 없으면 뷰어 쪽을 돌릴 수 없다")

_KST = datetime.timezone(datetime.timedelta(hours=9))
# 한국이 UTC보다 앞서므로 어긋남은 **KST 00~09시**에 난다. 옛 식이 그 구간에서
# 틀렸다는 것을 보이려면 그 시각을 반드시 표본에 넣어야 한다.
_INSTANTS = [
    "2026-08-29T19:11:00Z",  # KST 08-30 04:11 — 실제로 버그를 만난 시각
    "2026-08-29T15:00:00Z",  # KST 08-30 00:00 — 자정 경계
    "2026-08-29T14:59:59Z",  # KST 08-29 23:59:59 — 경계 직전
    "2026-08-30T02:00:00Z",  # KST 08-30 11:00 — 오전 9시 이후(옛 식도 맞던 구간)
    "2025-12-31T16:00:00Z",  # KST 2026-01-01 01:00 — 해 넘김
]
_ZONES = ["Asia/Seoul", "UTC", "America/New_York", "Europe/Berlin", "Pacific/Auckland"]


def _cut(name: str) -> str:
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


def _run(tz: str, instants) -> list:
    src = "const KST_OFFSET_MS = 9 * 60 * 60 * 1000;\n"
    for fn in ("kstDate", "todayKST", "ymd"):
        src += _cut(fn) + "\n"
    src += (f"const XS = {json.dumps(instants)};\n"
            "console.log(JSON.stringify(XS.map((x) => {\n"
            "  const d = new Date(x);\n"
            "  const realNow = Date.now;\n"
            "  Date.now = () => d.getTime();\n"
            "  const out = [todayKST(), ymd(d),\n"
            "    kstDate(Date.now()).toISOString().slice(0, 16).replace('T', ' ')];\n"
            "  Date.now = realNow;\n"
            "  return out;\n"
            "})));")
    tf = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    tf.write(src)
    tf.close()
    env = dict(os.environ, TZ=tz)
    try:
        r = subprocess.run([shutil.which("node"), tf.name], env=env,
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, f"node 실패({tz}):\n{(r.stderr or '')[:800]}"
        return json.loads(r.stdout)
    finally:
        os.unlink(tf.name)


def _expected(iso: str):
    kst = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(_KST)
    return [kst.strftime("%Y-%m-%d"), kst.strftime("%Y%m%d"),
            kst.strftime("%Y-%m-%d %H:%M")]


@pytest.mark.parametrize("tz", _ZONES)
def test_어느_시간대에서도_KST를_낸다(tz):
    got = _run(tz, _INSTANTS)
    want = [_expected(x) for x in _INSTANTS]
    bad = [f"{_INSTANTS[i]}: {got[i]} ≠ {want[i]}"
           for i in range(len(_INSTANTS)) if got[i] != want[i]]
    assert not bad, f"TZ={tz}에서 어긋난다:\n  " + "\n  ".join(bad)


def test_로컬_오프셋을_더_이상_쓰지_않는다():
    """옛 식이 되살아나면 UTC 브라우저에서만 통과하는 상태로 돌아간다."""
    for fn in ("kstDate", "todayKST", "ymd"):
        assert "getTimezoneOffset" not in _cut(fn), f"{fn}에 로컬 오프셋이 남아 있다"
    # 주석의 설명은 남긴다 — 근거가 사라지면 다음 사람이 같은 식을 다시 쓴다
    assert "getTimezoneOffset()`은 한국에서 **-540**" in _HTML


def test_세_곳이_같은_헬퍼를_쓴다():
    assert _HTML.count("kstDate(") >= 4, "시계·todayKST·ymd + 정의"
    assert "const KST_OFFSET_MS = 9 * 60 * 60 * 1000;" in _HTML


def test_조회_창이_KST_기준임을_밝혀_둔다():
    i = _HTML.index("function ymd(d)")
    assert "KST 달력 날짜" in _HTML[i - 300:i]


def test_시계_라벨이_KST라고_적혀_있다():
    """라벨과 값이 갈리면 안 된다 — 이 버그가 정확히 그 상태였다."""
    assert "SESSION · KST" in _HTML
