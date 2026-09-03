r"""뷰어 ※/⚠ 고지 ~103자리가 지키는 **사실**을 다음 PR(요약·분량 축소, −35~40%)
이전에 잠근다.

## 왜 필요한가

`docs/tool/index.html`의 고지 대부분은 장식이 아니라 **정직성 장치**다 —
조용한 절단 금지, 두 방향 한계(과대·과소) 동시 표기, 「잔액이 아닙니다」,
「실패 vs 없음」 구분. 다음 PR들이 문구를 다시 쓰면서 **낱말은 바뀌어도
괜찮지만 사실은 하나도 잃으면 안 된다**. 이 파일은 그 경계를 4개 층으로
나눠 잠근다. 이 과제 자체는 테스트와 픽스처만 추가한다 — `index.html`은
한 글자도 건드리지 않는다(이미 통과해야 하는 사실들의 스냅샷).

## 왜 「낱말 고정」이지 「동의어 허용」이 아닌가

셋 다 검토했다:

① 동의어 목록(예: "미확인"≈"확인 안 됨"≈"모름")은 재작성자가 다음 PR에서
   얼마든지 새 동의어를 추가해 잠금을 우회할 수 있다 — 잠금이 아니라
   장식이 된다.
② core↔뷰어 낱말 패리티가 이미 다른 테스트로 묶여 있다 — `미확인`·`생략`·
   `전부 표시` 같은 표현은 core의 「N건 중 최근 M건 표시 · P건 생략」과
   짝을 이룬다(CLAUDE.md 「확인 상한을 밝힌다」·「조용한 절단 두 곳」 항목).
   뷰어만 다른 낱말로 흩어지면 그 패리티가 조용히 깨진다.
③ "뜻 검사"(그 낱말이 실제로 맞는 사실을 가리키는가)는 이 파일의 **층 3**이
   맡는다 — 고정 픽스처를 렌더해 나온 **수량 토큰 집합**을 스냅샷과
   비교하므로, 낱말이 바뀌어도 그 낱말이 감싸는 숫자·단위가 사라지면 걸린다.

그래서 층 1·2는 **낱말 자체**를 고정하고(다음 PR이 문구를 다시 쓸 때
"이 낱말이 사라지면 실패"라는 신호를 준다), 층 3이 "그 낱말이 진짜 사실을
말하는가"를 뜻으로 검사한다. 낱말이 바뀌면 층 1·2가 먼저 알려주고, 사실이
바뀌면(같은 낱말이어도 숫자가 사라지면) 층 3이 알려준다 — 두 층이 서로
다른 실패 모드를 잡는다.

## 4개 층

- **층 1** — 함수 단위 정적 문자열 잠금(A 유형: 절단·상한). `_cut`으로 함수
  본문을 잘라 필수 정규식이 전부 있는지만 본다. 실행하지 않는다.
- **층 2** — 패널 필수 낱말(B/C/D/F 유형). 일부는 함수 본문에 리터럴로
  없고 이름이 같은 문자열 **상수**를 통해서만 들어온다(`MZN_NOT_BALANCE`
  등) — 그런 경우 상수 참조를 상수의 실제 정의로 치환한 확장 텍스트에
  대고 검사한다(아래 `_expand_consts`).
- **층 3** — 뜻 검사. 순수 함수 8개를 고정 픽스처로 실제 렌더해, 태그를
  지운 뒤 수량 토큰(`\d[\d,]*\s*(건|주|%|년|개|명|종|기간|원)`)의 **집합**을
  `tests/fixtures/viewer_notice_facts.json`과 비교한다. 다음 PR이 "정정
  3건"을 "정정 있음"으로 뭉개면 토큰 집합이 줄어 걸린다.
- **층 4** — 새 조용한 절단 방지. `render`/`load` 접두 함수 + `…HTML` 계열
  함수(선언·화살표 둘 다) 61개 전수에서 모든 `.slice(0, N)`·`.slice(-N)`이
  실제로 그 슬라이스를 가리키는 절단 고지와 **식별자로 짝지어지는지** 본다
  (아래 "층4 원장" 절 — 리뷰에서 고정폭 창의 함정이 발견돼 식별자 짝
  맞추기로 다시 짰다).

## 층 3 픽스처와 용어 사전(PR-C/PR-V)의 상호작용

이 저장소는 PR-C(core 해설)·PR-V(뷰어 용어 사전 툴팁)를 이미 포함한다 —
`glossStaticHTML`/`proseTextHTML`이 일부 고지 문구의 용어를 `<span
class="term">낱말<span class="term-def">…풀이…</span></span>`로 감싼다.
층 3이 태그를 지우고 수량 토큰을 뽑을 때 이 감싸기 자체는 문제가 안 된다
(태그를 지우면 낱말과 풀이가 그대로 텍스트에 남는다). 다만 **풀이(term-def)
안에 숫자가 섞여 있으면** 토큰 집합이 픽스처 입력과 무관하게 오염될 수
있어, `_strip_tags`는 태그만 지우고 `term-def`의 텍스트도 함께 남기지만
이 스냅샷의 8개 함수 중 어느 것도 현재 `glossStaticHTML`/`proseTextHTML`을
거치며 **용어 사전이 실제로 채워진 상태**로 실행되지 않는다 — `DATA`(용어
사전 원본)를 채우지 않고 실행하면 `glossTermsHTML`은 빈 사전이라 아무
낱말도 감싸지 않고 원문을 그대로 반환한다(`docs/tool/index.html`의
`glossStaticHTML`/`proseTextHTML` 정의 참고 — `DATA.glossary`가 없으면
빈 dict로 폴백). 즉 이 스냅샷은 **용어 사전 비활성 상태**의 출력이다.
차후 PR이 `DATA.glossary`를 채운 상태로 이 함수들을 렌더하게 되면, 태그를
지운 뒤 `term-def`의 숫자가 섞여 들어올 수 있으므로 그때는 `_strip_tags`가
`<span class="term-def">…</span>` 구간을 통째로 제거하도록 넓혀야 한다 —
지금은 필요하지 않아 넣지 않았다(요구하지 않는 방어 코드는 추가하지
않는다).

## 알려진 결함 (xfail 대상)

- ~~**PR-N1** `loadDeepBlocks`의 catch 8곳이 `조회 실패: ${e.message}`만
  적고 정직 문구가 없다~~ → **PR-N1이 고쳤다**(아래 F 절 참고). 8곳 전부
  `fetchFailHTML(`을 태워 「자료가 없다는 뜻이 아닙니다」를 동반한다. 이
  결함의 잠금은 `test_F_loadDeepBlocks_catch_8곳이_fetchFailHTML을_탄다`가
  이어받는다(이름을 바꾼 것이 아니라 **정의를 뒤집었다** — 옛 이름
  `_에코_catch는_8곳이다`는 "8곳이 문제 문구를 낸다"를 잠갔고, 새 이름은
  "8곳이 고쳐진 호출을 탄다"를 잠근다). (나머지 3곳은 `.catch(() => {})`로
  완전히 조용하다 — 이건 이 결함과 다른 종류이고, 부수적 보강 블록이
  실패해도 화면에 아무 주장도 하지 않으므로 이 PR의 잠금 대상이 아니다.)
- ~~**PR-N4** `loadHoldings`의 `reps….slice(0, 5)`·`pts.slice(-10)`에 절단
  고지가 없다~~ → **PR-N4가 고쳤다**(「보고자 N명 중 M명 표시 · P명 생략」·
  「보고 N건 중 최근 M건 표시」). xfail 표시를 뗐고 테스트 본문은 그대로다 —
  이제 정상 통과가 잠금이다. **xfail은 이 파일에 더 이상 없다.**

## F 전수 — 브리프의 "catch 블록이 있는 load… 함수 전부"를 실측으로 좁힌 이유

브리프는 F를 "catch 블록이 있는 `load…` 함수 전부에 `fetchFailHTML(`이
있는지"로 적었다. 실제로 `_cut`으로 전수를 훑으면 `catch`(형태 무관)가
있는 `load…` 함수는 `loadFavs`·`loadSnapStore`(로컬스토리지, DART 무관)·
`loadFundDiversionGate`·`loadCapitalBackflowGate`(원문 재분류 실패 시 이미
`…원문에서 직접 확인하세요`라는 동등한 정직 문구를 자체적으로 낸다)·
`loadDeepBlocks` 다섯뿐이다. 이 다섯에 문자 그대로 "`fetchFailHTML(` 존재"를
요구하면 **5개 전부**가 걸린다 — 브리프가 말한 "알려진 결함은 2개뿐"과
모순된다. 실측(`loadDeepBlocks` 안의 catch 11곳을 중괄호 균형으로 전부
잘라 봄)으로 좁히면: `loadDeepBlocks`는 catch 8곳(정직 문구 부재)·침묵
3곳(`.catch(() => {})`, `loadRelatedPartyCore`·`loadEarningsShockCore`·
`loadAssetTransferCore`)으로 나뉘고, 침묵 3곳은 "실패를 없음으로 속이는"
결함이 아니라 "보강 블록이 조용히 안 나타나는" 별개의 설계다(이미 다른
컨테이너가 없으면 패널 자체를 안 그리는 조건부 렌더링 대상). 그래서 F는
`loadDeepBlocks`의 catch 8곳으로 **좁혀서** 구현했다 — 이것이 PR-N1의
정의역이다.

**PR-N1 수정과 그 리뷰(2026-09-03)**: 최초 수정은 8곳을 전부
`fetchFailHTML(e.message)` 호출로 바꿨는데, 그러면 catch 본문에서 `조회
실패` 리터럴이 사라져 위 회귀 테스트(옛 `_에코_catch는_8곳이다`가 "8곳"을,
`_침묵_catch_3곳은…`이 "3곳"을 그 리터럴 유무로 세고 있었다)가 깨졌다.
1차 수정은 각 catch에 `// 조회 실패 ≠ 자료 없음` 인라인 주석을 남겨
리터럴 카운트를 맞췄는데, **이건 테스트를 통과시키려고 코드에 문구를
심은 것**이라 컨트롤러 리뷰에서 거짓 잠금(false lock)으로 지적됐다 —
테스트가 "고쳐졌다"고 말하는 근거가 실행되는 호출이 아니라 주석이었다.
그래서 주석을 지우고, 테스트를 **정의를 뒤집어** 다시 짰다: "8곳이
`조회 실패` 리터럴을 낸다"(결함이 존재한다는 잠금) →
"8곳이 `fetchFailHTML(`을 탄다 + `조회 실패:` 리터럴이 0번 나온다"(결함이
고쳐졌다는 잠금). "침묵 3곳"의 판정 기준도 `조회 실패` 부재에서
`fetchFailHTML(` 부재로 옮겼다 — 옛 기준을 그대로 두면 고쳐진 8곳도
"침묵"으로 잘못 세게 된다(둘 다 이제 `조회 실패` 리터럴이 없으므로).
`loadFundDiversionGate`·`loadCapitalBackflowGate`는 catch 본문에 `직접
확인하세요`가 이미 있어 정직하고(별도 회귀 테스트로 잠근다), `loadFavs`/
`loadSnapStore`는 DART 데이터를 다루지 않아 범위 밖이다.

## D 전수 — "패널 렌더 함수 8개"도 실측과 다르다

브리프는 "메자닌·희석·재무·자금사용·소유보고·감사·패턴·자금유출" 8개
함수마다 `판정이 아닙니다|판단이 아닙니다|사실 표기입니다`가 있는지
보라고 적었다. 실제로 이름 붙여 찾아 `_cut`으로 확인하면:

    mezzanineBlockHTML     "판단이 아닙니다"      있음
    dilutionBlockHTML      "판단이 아닙니다"      있음
    loadFinancialCore      "사실 표기입니다"      있음
    dividendPanelHTML      "판정이 아닙니다"      있음 (배당 — 브리프 8개엔 없지만 같은 유형)
    compareActors          "판정이 아닙니다"      있음 (겸직 비교 — 같은 유형)
    fundChainPanelHTML     —                      없음
    loadHoldings           —                      없음
    loadAuditOpinions      —                      없음
    capitalBackflowCardHTML —                     없음

브리프가 말한 "패널 렌더 함수 8개"라는 목록 자체가 실코드와 안 맞는다
(정확히 8개도 아니고, 이름도 일부는 실존하지 않는 대응이다). 이 과제는
"현재 코드로 통과"가 요구조건이라 없는 결함을 3~4개 더 xfail로 발명하지
않는다 — 대신 **실제로 존재하는 다섯 곳**만 D로 잠그고, 나머지 넷은 이
파일의 검사 대상에서 뺀다(추가하지 않는다는 원칙, `없는 것은 목록에서
빼고 report에 적는다`를 D에도 그대로 적용). 넷 다 무판정 원칙 자체를
어기는 것은 아니다(점수·등급 문구가 없다는 것은 `test_golden_output_hygiene.py`
가 이미 전역으로 지킨다) — 다만 "이것은 사실 표기이지 판정이 아니다"라는
**명시적** 문장이 그 함수 자체에는 없다는 뜻이다. 다음 PR이 다룰 후보로
report에 남긴다.

## 층4 원장 — 리뷰 라운드1에서 다시 짠 것과 그 이유(창 규칙 포함)

최초 구현은 두 가지가 헐거웠다(리뷰 지적). ① `_NOTICE_WORD_RE`(외|생략|
미확인|숨김|표시|확인 시도|중 최근)를 **함수 전체**에 걸어, 그 슬라이스와
무관한 낱말이 우연히 "고지가 있다"로 통과시켰다 — 실측: `loadAuditOpinions`
는 「적정 **외** 감사의견」(무관), `renderFeed`는 `${CUR.truncated}건 중
최근`(**다른** 절단 — 스캔 전체 상한이지 `list.slice(0, 200)`의 상한이
아니다)이 각각 구했다. 조사 중 세 번째도 나왔다 — `loadCapitalBackflowGate`
의 유일한 매치는 주석 「자리**표시**자가 스피너라…」("표시"가 부분 일치)
였다. ② 함수 목록이 `render|load` 접두 30개뿐이라 전체 슬라이스 52곳 중
6곳만 봤다.

두 가지 모두 고쳤다:

- **절단 낱말을 실제 모양으로 좁힌다**(`_NOTICE_RE`) — 이 코드베이스의
  진짜 절단 고지는 전부 "건" 바로 옆이거나(「건 생략」·「건 표시」·「건
  숨김」·「건 미확인」·「건 중 최근」) "외" 바로 뒤에 보간이 온다(「외
  ${」). 「자리표시자」·「적정 외」는 이 모양이 아니라 걸러진다.
- **식별자로 짝을 맞춘다**(`_slice_paired`) — 슬라이스의 원본 변수(예
  `list`)와 경계값(예 `200`)이 그 고지 문구 옆(±100자, 문구 기준)에
  실제로 나오는지 본다. **고정폭 창은 쓰지 않는다** — `dilutionBlockHTML`
  처럼 슬라이스와 그 고지가 469자, `mezzanineBlockHTML`처럼 2,104자
  떨어져 있는 **정상** 사례가 있어(둘 다 이미 층1이 잠근 진짜 고지다),
  고정폭 창을 쓰면 창을 아무리 넉넉히 잡아도 어느 값에서든 정상 사례를
  놓치거나(너무 좁으면) 무관한 낱말을 다시 구제하는(너무 넓으면 함수
  전체와 같아진다) 딜레마에 빠진다. 식별자 짝 맞추기는 거리와 무관하게
  "이 고지가 **이 슬라이스의** 숫자를 말하는가"만 본다.
- **함수 목록을 넓힌다**(`_all_render_load_funcs`) — `render|load` 접두 +
  `function \w*HTML\w*(...)` 선언 + `const \w*HTML\w* = (async )?(...) =>
  {...}` 화살표(브리프가 예로 든 형태이나 이 코드베이스에는 현재 0개) —
  30개 → 61개.
- **원리적으로 같은 5번째 예외**를 추가했다(`_is_split_pair`) — 브리프의
  4개(`slice(0,1)`·`slice()`·`slice(1)`·`slice(-1)`)는 전부 "정보가 안
  사라진다"는 같은 원리다. `.slice(0, VAR)`와 짝인 `.slice(VAR)`(같은
  식별자, 단일 인자)가 같은 함수에 있으면 원본을 정확히 둘로 나눠 **둘
  다 쓰는 것**이다(`leadSentenceHTML`의 lead/rest) — 절단이 아니라 분할.

다시 짠 뒤 나온 결과는 5개 함수였다 — `loadHoldings`·`loadFundDiversionGate`
(잘린 개수를 전체처럼 찍는다, 「없다」보다 나쁘다)·`loadAuditOpinions`
(구조적으로 오늘은 무해하지만 그 사실을 코드가 말하지 않는다)·`renderFeed`
(피드 200행 초과가 조용히 잘린다, 스캔 전체 절단 안내와는 별개 사실)·
`mezzanineBlockHTML`(문자열 **값** 절단 2곳 — 같은 함수의 다른 슬라이스는
이미 층1이 잠갔다). **PR-N4가 다섯 곳 전부에 고지를 붙여 `_LAYER4_KNOWN_GAPS`
는 비었다**(상한 값은 하나도 안 바꿨다). 그래서
`test_층4_원장_항목은_아직_고지가_없다`는 파라미터가 없어 건너뛴다 — 원장이
비었다는 사실 자체가 그 테스트가 말하려던 것이고, 새 절단이 생기면 집합 동등
검사(`test_층4_slice_옆에_절단_고지가_있다`)가 먼저 걸린다.
"""
import json
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = _ROOT / "docs" / "tool" / "index.html"
_FIXTURE = _ROOT / "tests" / "fixtures" / "viewer_notice_facts.json"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node가 없어 뷰어 JS를 실행할 수 없다"
)


def _html() -> str:
    return _HTML.read_text(encoding="utf-8")


# ── 하네스 (test_viewer_fetch_failure.py / test_viewer_mezzanine_sort.py 관례 이식) ──

def _cut(html: str, name: str) -> str:
    """`function name(...) { ... }` 를 중괄호 균형으로 잘라낸다."""
    m = re.search(r"^(async )?function " + re.escape(name) + r"\s*\(", html, re.M)
    assert m, "함수를 찾지 못했다: " + name
    i = m.start()
    depth = 0
    started = False
    for j in range(i, len(html)):
        if html[j] == "{":
            depth += 1
            started = True
        elif html[j] == "}":
            depth -= 1
            if started and depth == 0:
                return html[i:j + 1]
    raise AssertionError("중괄호가 맞지 않는다: " + name)


def _cut_decl(html: str, name: str) -> "str | None":
    """`const/let/var NAME = …;` 선언 하나 또는 `function NAME(...)`을 잘라 온다."""
    m = re.search(r"^(?:const|let|var)\s+" + re.escape(name) + r"\s*=", html, re.M)
    if not m:
        if re.search(r"^(?:async )?function\s+" + re.escape(name) + r"\s*\(", html, re.M):
            return _cut(html, name)
        return None
    i = m.start()
    eol = html.index("\n", i)
    line = html[i:eol]
    if line.rstrip().endswith(";") and line.count("{") == line.count("}"):
        return line
    depth, j, in_s, q = 0, i, False, ""
    while j < len(html):
        c = html[j]
        if in_s:
            if c == "\\":
                j += 2
                continue
            if c == q:
                in_s = False
        elif c in "\"'`":
            in_s, q = True, c
        elif c in "{[(":
            depth += 1
        elif c in "}])":
            depth -= 1
        elif c == ";" and depth == 0:
            return html[i:j + 1]
        j += 1
    return None


def _node(code: str):
    tf = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    tf.write(code)
    tf.close()
    try:
        return subprocess.run([shutil.which("node"), tf.name], capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
    finally:
        pathlib.Path(tf.name).unlink(missing_ok=True)


# esc()는 정규식 리터럴 안에 따옴표가 있어 중괄호 기반 `_cut`이 문자열 시작으로
# 오인한다(test_viewer_mezzanine_sort.py의 기존 교훈) — 심는다.
_ESC_SHIM = 'const esc = (s) => String(s).replace(/[&<>"]/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", \'"\': "&quot;" }[m]));\n'


def _normalize_concat(text: str) -> str:
    """뷰어 소스는 긴 문구를 `` `...` + `...` `` 처럼 여러 백틱 리터럴로
    쪼개 이어붙인다(가독성을 위한 줄바꿈). 실행용 JS 소스는 그대로 둬야
    하지만(`_cut`/`_run_pure`), **사실 검사용 정적 텍스트 매칭**에서는 이
    이어붙임을 하나로 합쳐야 한다 — 안 그러면 "발행이 없다는 " + "뜻이
    아닙니다"처럼 실제로는 한 문장인데 소스에서만 둘로 잘린 문구를
    정규식이 놓친다. 이 함수는 텍스트 비교 전용이며 `_cut`이 돌려주는
    실행 가능한 JS 소스에는 절대 적용하지 않는다.
    """
    return re.sub(r"`\s*\+\s*`", "", text)


def _run_pure(func_heads: list, calls: dict, extra_pre: str = "") -> dict:
    """`func_heads`(함수명 목록)를 실제 소스에서 잘라 실행하고, `calls`
    (표현식 이름→JS 표현식 문자열)의 결과를 dict로 돌려준다. 부족한 전역
    참조는 ReferenceError를 보고 실제 소스에서 자동으로 끌어온다(하드코딩
    셔틀 없이 실코드 그대로 실행 — test_viewer_mezzanine_sort.py의 `_viewer`
    관례).
    """
    html = _html()
    src = "\n".join(_cut(html, f) for f in func_heads)
    body = ",\n".join(f"  {json.dumps(k)}: {v}" for k, v in calls.items())
    js_tail = "\nconsole.log(JSON.stringify({\n" + body + "\n}));\n"
    pre = extra_pre
    for _ in range(30):
        js = _ESC_SHIM + pre + src + js_tail
        r = _node(js)
        if r.returncode == 0:
            return json.loads(r.stdout)
        m = re.search(r"ReferenceError: (\w+) is not defined", r.stderr or "")
        if not m:
            raise AssertionError("node 실패:\n" + (r.stderr or "")[:2500])
        name = m.group(1)
        if name == "esc":
            raise AssertionError("esc 셔틀이 없다 — _ESC_SHIM 확인")
        d = _cut_decl(html, name)
        assert d is not None, f"뷰어에서 {name} 선언을 찾지 못했다"
        pre = d + "\n" + pre
    raise AssertionError("보조 선언을 30번 끌어와도 안 돈다")


def _expand_consts(html: str, body: str, names: list) -> str:
    """`body` 안의 상수 식별자 참조를 그 상수의 실제 정의 텍스트로 치환한
    확장 텍스트를 돌려준다. `MZN_NOT_BALANCE`처럼 함수 밖에 정의된 문자열
    상수를 함수가 이름으로만 참조할 때, 그 상수가 지키는 사실(예: 「잔액이
    아닙니다」)이 함수 자체의 소스에는 리터럴로 없어 정적 검사가 놓친다 —
    참조 횟수만큼 정의를 치환해 넣으면 "이 사실이 몇 곳에서 보호되는가"를
    문자 그대로 셀 수 있다.
    """
    out = body
    for name in names:
        decl = _cut_decl(html, name)
        assert decl is not None, f"상수를 찾지 못했다: {name}"
        out = re.sub(r"\b" + re.escape(name) + r"\b", lambda _m, d=decl: d, out)
    return out


def _notice_members(html: str) -> dict:
    """`const NOTICE = {…}` 의 문자열 멤버를 {KEY: 값}으로 읽는다.

    `_expand_consts`가 **함수 밖 문자열 상수**(`MZN_NOT_BALANCE` 등)를 이름
    참조에서 정의로 바꿔 넣듯이, 이건 같은 문제의 **객체 멤버** 판이다 —
    PR-N4가 네 패널(`fundChainPanelHTML`·`loadHoldings`·`loadAuditOpinions`·
    `capitalBackflowCardHTML`)의 무판정 문구를 `${NOTICE.NO_JUDGMENT}` 참조로
    넣어, 함수 본문에는 리터럴이 없다. 참조를 값으로 펴야 D 검사가 그
    문구를 볼 수 있다.
    """
    decl = _cut_decl(html, "NOTICE")
    assert decl is not None, "NOTICE 상수를 찾지 못했다"
    out = {}
    for m in re.finditer(r"^\s*(\w+):\s*([\"`'])", decl, re.M):
        key, quote = m.group(1), m.group(2)
        i = m.end()
        buf = []
        while i < len(decl):
            c = decl[i]
            if c == "\\":
                buf.append(decl[i:i + 2])
                i += 2
                continue
            if c == quote:
                break
            buf.append(c)
            i += 1
        out[key] = "".join(buf)
    assert out, "NOTICE에서 문자열 멤버를 하나도 못 읽었다 — 정규식이 낡았다"
    return out


def _expand_notice(html: str, body: str) -> str:
    """`${NOTICE.X}`·`NOTICE.X` 참조를 그 상수의 실제 문자열로 바꾼다."""
    for key, val in _notice_members(html).items():
        body = body.replace("${NOTICE." + key + "}", val).replace("NOTICE." + key, val)
    return body


def _strip_tags(html_fragment: str) -> str:
    return re.sub(r"<[^>]*>", " ", html_fragment)


_QTY_RE = re.compile(r"\d[\d,]*\s*(?:건|주|%|년|개|명|종|기간|원)")


def _qty_tokens(text: str) -> list:
    """태그를 지운 텍스트에서 수량 토큰(숫자+단위)만 뽑는다. `term-def`
    (용어 사전 툴팁)의 숫자가 섞여 들어오는 것을 막으려면 태그 제거
    **전에** `<span class="term-def">…</span>` 구간을 먼저 들어내야 하는데,
    이 스냅샷의 8개 함수는 용어 사전이 비활성 상태(`DATA.glossary`
    미충전)로 실행되어 `term`/`term-def` 마크업 자체가 생기지 않는다(모듈
    docstring 참고) — 그래도 방어적으로 먼저 제거해 둔다(생겨도 안전).
    """
    no_termdef = re.sub(r'<span class="term-def"[^>]*>.*?</span>', "", text, flags=re.S)
    plain = _strip_tags(no_termdef)
    return sorted(set(_QTY_RE.findall(plain)))


# ══════════════════════════════════════════════════════════════════════════
# 층 1 — 함수 단위 정적 문자열 잠금 (A 유형: 절단·상한)
# ══════════════════════════════════════════════════════════════════════════

FUNC_REQUIRED = {
    # WATCH 렌더은 별도 함수가 아니라 renderDash 안에 있다(실코드 확인,
    # 2026-09-03) — 브리프의 "WATCH 렌더 함수"를 renderDash에 합쳤다.
    "renderDash": [
        r"\$\{CUR\.truncated\}건",
        r"coveredFrom\(items\)",
        r"빠졌",
        r"crisisEvents\.length - 6",
    ],
    "patternEvidenceHTML": [r"외 \$\{rest\}건"],
    "capitalBackflowCardHTML": [
        r"\$\{totalCount\}건 중",
        r"\$\{_unreviewed\}건 미확인",
    ],
    # ≈9개 — 실제 본문을 읽고 절단·상한을 말하는 문자열을 전수 확인했다.
    # 리뷰 반영: 「생략」·「제외:」처럼 낱말만 있고 옆의 `${…}` 변수를 안
    # 물던 항목을 실제 소스의 변수까지 포함하도록 좁혔다 — 그래야 그
    # 낱말이 "이 함수의 이 절단"을 가리킨다는 것을 정적으로도 보장한다.
    "mezzanineBlockHTML": [
        r"정정 \$\{d\.filings_amended\}건",
        r"제외: \$\{esc\(ex\.join",
        r"만기일 경과",
        r"\bEB\b",
        r"MZN_ISSUE_MAX",
        r"\$\{d\.issues\.length - MZN_ISSUE_MAX\}건 생략",
        r"발행이 없다는 뜻이 아닙니다",
        r"서로 다른 원장",
        r"판단이 아닙니다",
    ],
    "mezzanineFilingsHTML": [
        r"전체 \$\{",
        r"\$\{rows\.length\}건 표시",
        r"\$\{amended\}건 숨김",
    ],
    "dilutionBlockHTML": [
        r"일자 미기재",
        r"외 \$\{top\.length - 8\}종",
        r"조회 창",
        r"원장에는",
    ],
    "loadAuditOpinions": [r"조회 범위 안에서", r"더 길 수"],
    "detailCapNote": [r"건 중 최근", r"건 미확인"],
}


@pytest.mark.parametrize("func,patterns", list(FUNC_REQUIRED.items()), ids=list(FUNC_REQUIRED.keys()))
def test_층1_함수_필수_문자열(func, patterns):
    body = _normalize_concat(_cut(_html(), func))
    missing = [p for p in patterns if not re.search(p, body)]
    assert not missing, f"{func}에서 사라진 사실 패턴: {missing}"


# ══════════════════════════════════════════════════════════════════════════
# 층 2 — 패널 필수 낱말 (B/C/D/F 유형)
# ══════════════════════════════════════════════════════════════════════════

def test_층2_mezzanineBlockHTML_필수_낱말():
    html = _html()
    body = _cut(html, "mezzanineBlockHTML")
    expanded = _normalize_concat(
        _expand_consts(html, body, ["MZN_NOT_BALANCE", "MZN_WINDOW_CAVEAT"]))
    assert expanded.count("잔액이 아닙니다") >= 2, (
        "MZN_NOT_BALANCE 참조가 2곳(대기물량 블록·만기 블록) 미만이다")
    for must in ("상한", "서로 다른 원장", "판단이 아닙니다", "발행이 없다는 뜻이 아닙니다"):
        assert must in expanded, f"mezzanineBlockHTML에서 사라진 낱말: {must}"
    # pair — 과대(「상한입니다」)·과소(MZN_WINDOW_CAVEAT의 「빠집니다」) 두
    # 방향이 같은 함수 안에 동반돼야 한다. 하나만 남으면 반쪽짜리 정직이다.
    assert "상한" in body and "빠집니다" in expanded


def test_층2_mezzanineBlockHTML_상수_자체():
    html = _html()
    caveat = _cut_decl(html, "MZN_WINDOW_CAVEAT")
    not_balance = _cut_decl(html, "MZN_NOT_BALANCE")
    assert "창" in caveat and "빠집니다" in caveat
    assert "잔액이 아닙니다" in not_balance and "발행결정" in not_balance


def test_층2_dilutionBlockHTML_pair():
    body = _cut(_html(), "dilutionBlockHTML")
    assert "조회 창" in body and "변동이 없습니다" in body


def test_층2_compareActors_필수_낱말():
    body = _cut(_html(), "compareActors")
    assert "동명이인" in body
    assert "연결 없음" in body


# ── F 전수 — loadDeepBlocks의 catch 8곳(모듈 docstring 참고) ──

def _catch_bodies(src: str) -> list:
    """`catch (e) { ... }`·`.catch((e) => { ... })` 양쪽 형태의 본문을
    중괄호 균형으로 전부 잘라 리스트로 돌려준다.
    """
    out = []
    for m in re.finditer(r"\bcatch\b", src):
        i = src.find("{", m.end())
        if i == -1:
            continue
        depth = 0
        for j in range(i, len(src)):
            if src[j] == "{":
                depth += 1
            elif src[j] == "}":
                depth -= 1
                if depth == 0:
                    out.append(src[i:j + 1])
                    break
    return out


def _loaddeepblocks_catches() -> list:
    return _catch_bodies(_cut(_html(), "loadDeepBlocks"))


def test_F_loadDeepBlocks_catch_8곳이_fetchFailHTML을_탄다():
    """PR-N0가 기록한 결함 — 이 함수의 catch 8곳이 `조회 실패: ${e.message}`만
    적고 「자료가 없다는 뜻이 아닙니다」류 정직 문구가 없었다 — 을 PR-N1이
    고쳤다. 이 테스트는 옛 `test_F_loadDeepBlocks_에코_catch는_8곳이다`를
    이어받되 **정의를 뒤집었다**: 옛 버전은 "8곳이 `조회 실패` 리터럴을
    낸다"(결함이 존재한다)를 잠갔고, 이 버전은 "8곳이 실제로
    `fetchFailHTML(`을 호출하고, 옛 에코 리터럴은 한 번도 안 남는다"(결함이
    고쳐졌다)를 잠근다.

    PR-N1의 1차 시도는 호출부만 바꾸고 각 catch에 `// 조회 실패 ≠ 자료
    없음` 주석을 남겨 옛 리터럴 카운트("8곳")를 맞췄는데, 그건 **테스트를
    통과시키려고 코드에 문구를 심은 것**이라 거짓 잠금이다 — 주석은
    실행되지 않으므로 "고쳐졌다"는 증거가 될 수 없다. 리뷰 지적으로
    주석을 지우고 이 테스트로 대체했다: 통과 여부가 실제 호출(`fetchFailHTML(`)
    존재와 옛 리터럴(`조회 실패:`) 부재라는 **실행 가능한 사실**에만
    좌우된다.
    """
    catches = _loaddeepblocks_catches()
    fetch_fail = [b for b in catches if "fetchFailHTML(" in b]
    assert len(fetch_fail) == 8, [b[:60] for b in catches]
    body = _cut(_html(), "loadDeepBlocks")
    assert "조회 실패:" not in body, (
        "옛 에코 리터럴(또는 그것을 흉내 낸 주석)이 아직 loadDeepBlocks에 남아 있다")


def test_F_loadDeepBlocks_침묵_catch_3곳은_실패를_주장하지_않는다():
    """`loadRelatedPartyCore`/`loadEarningsShockCore`/`loadAssetTransferCore`의
    `.catch(() => {})`는 완전히 비어 있다 — 위에서 고친 8곳(전부
    `fetchFailHTML(`을 탄다)과 다른 부류(주장 자체가 없다)임을 고정한다.
    ⚠ "침묵"의 판정 기준을 PR-N1에서 `조회 실패` 부재 → `fetchFailHTML(`
    부재로 옮겼다 — 옛 기준을 그대로 두면 고쳐진 8곳도 옛 리터럴이 없으니
    "침묵"으로 잘못 세게 된다. 이 셋에 나중에 `fetchFailHTML(` 호출이
    생기면 이 회귀 검사가 F의 정의역이 바뀌었음을 알려준다.
    """
    catches = _loaddeepblocks_catches()
    silent = [b for b in catches if "fetchFailHTML(" not in b]
    assert len(silent) == 3
    for b in silent:
        assert b.strip() in ("{}", "{ }")


def test_F_loadFundDiversionGate와_loadCapitalBackflowGate는_이미_정직하다():
    """이 둘도 `catch`가 있지만 `조회 실패` 에코가 아니라 `…직접
    확인하세요`라는 동등한 정직 문구를 이미 낸다 — F의 좁힌 범위 밖이지만
    "이미 정직함"을 회귀로 고정해 둔다.
    """
    html = _html()
    for fn in ("loadFundDiversionGate", "loadCapitalBackflowGate"):
        body = _cut(html, fn)
        assert "직접 확인하세요" in body, f"{fn}의 정직 문구가 사라졌다"


def test_없음_문장에_실패_낱말이_섞이지_않는다():
    """core 원칙과 같은 대칭: 「없다」와 「못 받았다」는 다른 사실이다. 같은
    줄에서 「없습니다」와 「실패」가 함께 쓰이면 두 사실이 뒤섞인 것이다.
    """
    bad = [ln.strip() for ln in _html().splitlines()
           if "없습니다" in ln and "실패" in ln]
    assert not bad, bad


# ── D 전수 — 실제로 무판정 문구가 있는 다섯 함수(모듈 docstring 참고) ──

D_JUDGMENT_RE = r"판정이 아닙니다|판단이 아닙니다|사실 표기입니다"

D_FUNCS = (
    "mezzanineBlockHTML",
    "dilutionBlockHTML",
    "loadFinancialCore",
    "dividendPanelHTML",
    "compareActors",
    # ⚠ 아래 넷은 PR-N0가 「무판정 문구가 없다」고 적어 이 검사에서 빠져 있던
    # 자리다(모듈 docstring의 D 전수 절 참고). PR-N4가 넷 다 채웠고,
    # `${NOTICE.NO_JUDGMENT}` 참조로 넣었으므로 `_expand_notice`로 펴서 본다 —
    # 그러지 않으면 문구가 실제로 화면에 나가는데도 검사에는 안 보인다.
    "fundChainPanelHTML",
    "loadHoldings",
    "loadAuditOpinions",
    "capitalBackflowCardHTML",
)


@pytest.mark.parametrize("func", D_FUNCS)
def test_D_무판정_문구가_있다(func):
    html = _html()
    body = _expand_notice(html, _cut(html, func))
    assert re.search(D_JUDGMENT_RE, body), f"{func}에서 무판정 문구가 사라졌다"


def test_D_screen_sub_전역_고지():
    """정적 HTML의 `.screen-sub` 고지는 렌더 함수 밖이라 파일 전역에서 본다."""
    assert "종목을 입력하면 최근 공시를 훑어 신호를 감지합니다. 사실 관찰이며 판정이 아닙니다." in _html()


# ══════════════════════════════════════════════════════════════════════════
# 층 3 — 렌더 사실 스냅샷 (뜻 검사)
# ══════════════════════════════════════════════════════════════════════════

_LAYER3_FUNCS = (
    "mezzanineBlockHTML",
    "mezzanineFilingsHTML",
    "dilutionBlockHTML",
    "capitalBackflowCardHTML",
    "detailCapNote",
    "fetchFailHTML",
    "patternEvidenceHTML",
    "acquisitionFactsHTML",
)

# ── 픽스처 입력 — 절단·상한·정정·창 밖·미확인이 전부 발화하도록 구성 ──

def _mzn_filing(date, category, round_=None, amend=False, idx=0):
    return {
        "date": date, "category": category, "round": round_, "is_amendment": amend,
        "rcept_no": f"{date}{idx:06d}", "report_nm": f"{category} 공시 {idx}",
        "label": category,
    }


# 13건, 그중 정정 3건 — mezzanineFilingsHTML의 "전체 N건 중 M건 표시 ·
# 정정 P건 숨김"/"정정 P건 포함" 두 경로를 함께 확인한다(층3에서는
# hideAmend=False 호출만 쓰지만 정정 건수 자체는 필수 토큰).
_MZN_FILINGS = [
    _mzn_filing("20260801", "issue", None, False, 1),
    _mzn_filing("20260715", "refix", 2, False, 2),
    _mzn_filing("20260710", "refix", 2, True, 3),
    _mzn_filing("20260620", "exercise", 3, False, 4),
    _mzn_filing("20260615", "exercise", 3, False, 5),
    _mzn_filing("20260501", "exercise", None, True, 6),
    _mzn_filing("20260420", "redeem", 1, False, 7),
    _mzn_filing("20260410", "redeem", 1, False, 8),
    _mzn_filing("20260301", "resell", None, False, 9),
    _mzn_filing("20260210", "result", None, True, 10),
    _mzn_filing("20260115", "issue", None, False, 11),
    _mzn_filing("20260101", "refix", None, False, 12),
    _mzn_filing("20251215", "exercise", None, False, 13),
]

# 발행 조건 10건(MZN_ISSUE_MAX=8 초과 → "8건 표시 · 2건 생략"), EB 1건,
# 만기 경과는 overhang.excluded_matured로 별도 표기.
_MZN_ISSUES = [
    {
        "round": i + 1, "kind": "CB" if i % 3 else ("BW" if i % 3 == 1 else "EB"),
        "face_amount": 1_000_000_000 + i * 10_000_000,
        "offering": "사모", "coupon": 2.0, "ytm": 4.5,
        "pay_date": f"2026{(i % 9) + 1:02d}01", "maturity": f"2029{(i % 9) + 1:02d}01",
        "strike": 5000 - i * 50, "strike_label": "전환가액",
        "potential_shares": 200000 + i * 1000, "potential_pct_at_issue": 1.2 + i * 0.1,
        "exercise_from": "20270101", "exercise_to": "20281231",
        "exchange_target": ("교환대상 종목" if i == 2 else None),
        "detachable": None,
        "refix_field_absent": (i == 2),  # EB 1건은 리픽싱 항목 없음
        "refix_floor": (None if i == 2 else 3500 - i * 10),
        "refix_floor_pct": (None if i == 2 else 68.0 + i),
        "refix_sub70_limit": (500_000_000 if i == 0 else None),
        "use_of_funds": ["운영자금"] if i == 0 else [],
    }
    for i in range(10)
]

_MZN_D = {
    "filings_total": len(_MZN_FILINGS),
    "filing_counts": {"issue": 2, "refix": 3, "exercise": 4, "redeem": 2, "resell": 1, "result": 1},
    "filings_amended": 3,
    "byKind": {
        "CB": {"count": 4, "face": 4_000_000_000, "face_unknown": 1},
        "BW": {"count": 3, "face": 3_000_000_000, "face_unknown": 0},
        "EB": {"count": 3, "face": 3_000_000_000, "face_unknown": 0},
    },
    "overhang": {
        "common_total": 10_000_000,
        "rows": [
            {
                "round": 1, "kind": "CB", "maturity_unknown": False,
                "face": 1_000_000_000, "strike": 5000, "shares_at_strike": 200000,
                "floor": 3500, "floor_pct": 70.0, "shares_at_floor": 285714,
            },
            {
                "round": None, "kind": "BW", "maturity_unknown": True,
                "face": 500_000_000, "strike": 4000, "shares_at_strike": 125000,
                "floor": None, "floor_pct": None, "shares_at_floor": None,
            },
        ],
        "face_total": 1_500_000_000,
        "shares_at_strike": 325000,
        "pct_at_strike": 3.25,
        "shares_at_floor": 285714,
        "pct_at_floor": 2.86,
        "floor_unknown": 1,
        "excluded_matured": 1,   # 만기 경과 1건
        "excluded_eb": 1,        # EB 1건
    },
    "maturity": {"not_yet": 2, "passed": 1, "unknown": 1},
    "exercise_open": 2,
    "filings": _MZN_FILINGS,
    "issues": _MZN_ISSUES,
}


def _dilution_d():
    by_type = {}
    kinds = ["dilutive", "proportional", "decrease", "unknown"]
    # 10종(> 8) — "외 2종" 절단 유발
    for i in range(10):
        by_type[f"주식종류{i}"] = {
            "kind": kinds[i % 4], "count": i + 1, "shares": (i + 1) * 10000,
        }
    return {
        "inWindow": True,
        "buckets": {"dilutive": 500000, "proportional": 200000, "decrease": 10000, "unknown": 3000},
        "dilutivePct": 12.3,
        "byType": by_type,
        "undated": 1,          # 일자 미기재 1건
        "commonTotal": 10_000_000,
        "earliest": "20220101",
        "latest": "20260101",
    }


def _pattern_fixture():
    return {
        "name": "자금 역류", "description": "테스트 패턴",
        "signal_sequence": ["5.7"],
        "window_start": "20260101", "window_end": "20260901",
        "timeline_months": 12,
        "field_evidence": [], "checkpoints": [], "prose": "",
    }


def _pattern_events(n=5):
    """패턴 근거 5건 초과 → patternEvidenceHTML의 "외 N건" 절단 유발."""
    out = []
    for i in range(n):
        out.append({
            "rcept": f"2026060{i}000001", "date": f"2026060{i}",
            "nm": f"금전대여 결정 {i}",
            "signals": [{"key": "FUND_OUTFLOW", "label": "자금유출", "taxonomies": ["5.7"]}],
        })
    return out


def _capital_backflow_results(n=4):
    """유출 6건 중 4건 확인 — capitalBackflowCardHTML의 미확인 고지 유발."""
    out = []
    for i in range(n):
        out.append({
            "rcept": f"2026060{i}000002", "date": f"2026060{i}",
            "nm": f"금전대여 결정 {i}", "cls": "affiliated" if i < 2 else "subsidiary",
            "relation": "계열회사" if i < 2 else "종속회사",
            "counterparty": f"상대법인{i}",
        })
    return out


def _acquisition_results():
    return [
        {"rcept": "20260601000003", "date": "20260601", "nm": "타법인주식취득 A",
         "issuer": "비상장대상법인", "listing": "unlisted", "cls": "affiliated",
         "relation": "계열회사", "amount": "1,000,000,000", "ratio": "12.5"},
        {"rcept": "20260602000004", "date": "20260602", "nm": "타법인주식취득 B",
         "issuer": "상장대상법인", "listing": "listed", "cls": "affiliated",
         "relation": "계열회사", "amount": "2,000,000,000", "ratio": "8.0"},
        {"rcept": "20260603000005", "date": "20260603", "nm": "타법인주식취득 C",
         "issuer": None, "listing": "unknown", "cls": "unknown",
         "relation": None, "amount": None, "ratio": None},
    ]


def _generate_layer3_facts() -> dict:
    """층3 픽스처 8개를 실제로 렌더해 {함수명: [수량 토큰 목록]}을 만든다.
    fixture json은 이 함수의 출력을 손으로 커밋한 스냅샷이다(--update
    옵션은 두지 않는다 — 갱신은 의도적으로, 손으로 한다).
    """
    out = _run_pure(
        list(_LAYER3_FUNCS),
        {
            "mezzanineBlockHTML": f"mezzanineBlockHTML({json.dumps(_MZN_D, ensure_ascii=False)}, [\"BW\"])",
            "mezzanineFilingsHTML": f"mezzanineFilingsHTML({json.dumps(_MZN_FILINGS, ensure_ascii=False)}, \"date\", false)",
            "dilutionBlockHTML": f"dilutionBlockHTML({json.dumps(_dilution_d(), ensure_ascii=False)}, 3)",
            "capitalBackflowCardHTML": (
                f"capitalBackflowCardHTML({json.dumps(_pattern_fixture(), ensure_ascii=False)}, "
                f"{json.dumps(_pattern_events(5), ensure_ascii=False)}, "
                f"{json.dumps(_capital_backflow_results(4), ensure_ascii=False)}, 6, {{}})"
            ),
            "detailCapNote": 'detailCapNote({length: 4, total: 6})',
            "fetchFailHTML": 'fetchFailHTML("오늘 이 키의 조회 한도(20,000건)를 초과했습니다")',
            "patternEvidenceHTML": (
                f"patternEvidenceHTML({json.dumps(_pattern_fixture(), ensure_ascii=False)}, "
                f"{json.dumps(_pattern_events(5), ensure_ascii=False)})"
            ),
            "acquisitionFactsHTML": (
                f"acquisitionFactsHTML({json.dumps(_pattern_fixture(), ensure_ascii=False)}, "
                f"{json.dumps(_acquisition_results(), ensure_ascii=False)})"
            ),
        },
    )
    return {name: _qty_tokens(html_out) for name, html_out in out.items()}


@pytest.fixture(scope="module")
def layer3_facts():
    return _generate_layer3_facts()


def test_층3_고정_픽스처가_실제로_절단_경로를_발화한다(layer3_facts):
    """fixture 입력이 절단·상한·정정·창밖·미확인을 실제로 유발하는지 먼저
    확인한다 — 조건이 안 걸리면 스냅샷이 아무것도 보호하지 못한다.
    """
    # 개별 절단 문구는 원본 HTML을 다시 렌더해 직접 확인한다(토큰 집합만으로는
    # "생략"이라는 낱말 자체를 볼 수 없다 — 그건 층1이 이미 잠근다).
    out = _run_pure(
        list(_LAYER3_FUNCS),
        {"mzn": f"mezzanineBlockHTML({json.dumps(_MZN_D, ensure_ascii=False)}, [\"BW\"])"},
    )
    mzn_html = out["mzn"]
    assert "생략" in mzn_html, "발행 조건 10건 중 8건 초과가 절단을 유발하지 못했다"
    assert "정정" in mzn_html and "3건" in mzn_html
    assert "만기일 경과" in mzn_html and "1건" in mzn_html
    assert "EB" in mzn_html and "1건" in mzn_html

    out2 = _run_pure(
        list(_LAYER3_FUNCS),
        {"dil": f"dilutionBlockHTML({json.dumps(_dilution_d(), ensure_ascii=False)}, 3)"},
    )
    assert "외 2종" in out2["dil"]
    assert "일자 미기재 1건" in out2["dil"]

    out3 = _run_pure(
        list(_LAYER3_FUNCS),
        {"pat": (
            f"patternEvidenceHTML({json.dumps(_pattern_fixture(), ensure_ascii=False)}, "
            f"{json.dumps(_pattern_events(5), ensure_ascii=False)})"
        )},
    )
    assert "외 2건" in out3["pat"], "패턴 근거 5건 초과가 절단을 유발하지 못했다"

    out4 = _run_pure(
        list(_LAYER3_FUNCS),
        {"cb": (
            f"capitalBackflowCardHTML({json.dumps(_pattern_fixture(), ensure_ascii=False)}, "
            f"{json.dumps(_pattern_events(5), ensure_ascii=False)}, "
            f"{json.dumps(_capital_backflow_results(4), ensure_ascii=False)}, 6, {{}})"
        )},
    )
    assert "6건 중 최근 4건" in out4["cb"] and "2건 미확인" in out4["cb"]


def test_층3_수량_토큰_스냅샷_일치(layer3_facts):
    saved = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    for func in _LAYER3_FUNCS:
        got = set(layer3_facts[func])
        want = set(saved.get(func, []))
        assert got == want, (
            f"{func}의 수량 토큰 집합이 스냅샷과 다르다(사실이 늘거나 줄었다)\n"
            f"  없어진 것: {sorted(want - got)}\n  새로 생긴 것: {sorted(got - want)}"
        )


def test_층3_fixture_json이_비어있지_않다():
    saved = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    for func in _LAYER3_FUNCS:
        assert saved.get(func), f"{func}의 스냅샷 토큰 집합이 비어 있다 — 픽스처가 아무 사실도 안 만든다"


# ══════════════════════════════════════════════════════════════════════════
# 층 4 — 새 조용한 절단 방지
# ══════════════════════════════════════════════════════════════════════════

# ── 리뷰 라운드1 반영 — 이 절 전체를 다시 짰다 ──────────────────────────
#
# 지적 ① **낱말만 보면 무관한 낱말이 슬라이스를 "구제"한다.** 원래는
#   `_NOTICE_WORD_RE`(외|생략|미확인|숨김|표시|확인 시도|중 최근)를 함수
#   **전체**에 걸었다 — 그 슬라이스와 아무 상관 없는 낱말이 있어도
#   "고지가 있다"로 통과했다. 실측: `loadAuditOpinions`의 유일한 매치는
#   「적정 **외** 감사의견」("외"가 그냥 무관한 낱말), `renderFeed`의
#   유일한 매치는 `${CUR.truncated}건 중 최근`(**다른** 절단 — 스캔
#   전체가 얼마나 잘렸는지 안내이지 `list.slice(0, 200)`의 상한과 무관).
#   조사 중 세 번째도 나왔다 — `loadCapitalBackflowGate`의 유일한 매치는
#   주석 「자리**표시**자가 스피너라…」("표시"가 "자리표시자"의 부분
#   일치)였다.
#
#   두 겹으로 고쳤다:
#   (a) 절단 낱말을 **실제로 쓰이는 모양**으로 좁힌다(`_NOTICE_RE`). 이
#       코드베이스의 진짜 절단 고지는 전부 "건" 바로 옆이거나(「건
#       생략」·「건 표시」·「건 숨김」·「건 미확인」·「건 중 최근」) "외"
#       바로 뒤에 보간이 온다(「외 ${」). 「자리표시자」·「적정 외」는 이
#       모양이 아니라 걸러진다. 브리프의 낱말 자체(외·생략·미확인·숨김·
#       표시·확인 시도·중 최근)는 버리지 않았다 — 모양만 좁혔다.
#   (b) 그래도 남는 동형(`renderFeed`처럼 **진짜 모양인데 다른 절단을
#       가리키는** 경우)은 **식별자로 짝을 맞춘다**(`_slice_paired`) —
#       슬라이스의 원본 변수(`list`)·경계값(`200`)이 그 고지 문구 옆
#       (±100자)에 실제로 나오는지 본다. 이 식별자 짝 맞추기가 있으므로
#       고정폭 창(예: ±400자)에 기대지 않는다 — ②에서 보듯 정상 케이스도
#       슬라이스와 고지가 2천자 넘게 떨어져 있을 수 있어 창 크기 자체가
#       신뢰할 수 없는 신호였다.
#
# 지적 ② **함수 목록이 좁았다.** `render|load` 접두만 훑어 30개였다(전체
#   슬라이스 52곳 중 6곳만 검사 대상). `function \w*HTML\w*(...)` 선언과
#   `const \w*HTML\w* = (async )?(...) => {...}` 화살표 함수까지 넓혀
#   61개 함수를 훑는다(이 코드베이스에는 아직 후자가 0개이지만, 브리프가
#   명시적으로 요구한 형태라 규칙은 남겨 둔다 — 생기면 자동으로 잡힌다).
#   `dilutionBlockHTML`이 이 넓힌 목록으로 새로 들어왔는데, 슬라이스와
#   고지가 469자 떨어져 있어 고정폭 창이었다면 여전히 놓쳤을 사례다 —
#   식별자 짝 맞추기(①-b)가 거리와 무관하게 잡아낸다.
#
# 브리프가 든 4개 예외(단건 선택 `slice(0,1)`·전체 복사 `slice()`·첫
# 항목 제외 `slice(1)`·마지막 항목 `slice(-1)`)에 **5번째**를 원리적으로
# 추가했다 — `_is_split_pair`: `.slice(0, VAR)`의 짝인 `.slice(VAR)`(같은
# 식별자, 단일 인자)가 같은 함수에 있으면 원본을 정확히 둘로 나눠 **둘
# 다 쓰는 것**이다(`leadSentenceHTML`의 lead/rest — 절단이 아니라 분할).
# 브리프의 4개와 원리가 같다(정보가 안 사라진다는 점) — 새로 만든 게
# 아니라 같은 원칙을 다른 모양에 적용한 것이다.

_SLICE_RE = re.compile(
    r"\.slice\(\s*0\s*,\s*(?!1\s*\))([\w.]+)\s*\)"
    r"|\.slice\(\s*-(?!1\s*\))(\d+)\s*\)"
)

_NOTICE_RE = re.compile(
    r"외\s*\$\{"
    r"|건\s*생략"
    r"|건\s*미확인|미확인"
    r"|건\s*숨김"
    r"|건\s*표시"
    r"|확인 시도"
    r"|건\s*중\s*최근"
)

_RENDER_LOAD_FUNC_RE = re.compile(
    r"^(?:async )?function ((?:render|load)\w*)\s*\(", re.M)
_HTML_FUNC_DECL_RE = re.compile(r"^(?:async )?function (\w*HTML\w*)\s*\(", re.M)
_HTML_ARROW_RE = re.compile(
    r"^(?:const|let)\s+(\w*HTML\w*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>\s*\{", re.M)


def _all_render_load_funcs(html: str) -> list:
    names = set(m.group(1) for m in _RENDER_LOAD_FUNC_RE.finditer(html))
    names |= set(m.group(1) for m in _HTML_FUNC_DECL_RE.finditer(html))
    names |= set(m.group(1) for m in _HTML_ARROW_RE.finditer(html))
    return sorted(names)


def _cut_render_func(html: str, name: str) -> str:
    """`function name(...)` 선언과 `const name = ... => {...}` 화살표
    함수 둘 다 받는다 — `_cut`(함수 선언 전용)이 못 찾으면 `_cut_decl`로
    넘어간다.
    """
    if re.search(r"^(?:async )?function " + re.escape(name) + r"\s*\(", html, re.M):
        return _cut(html, name)
    b = _cut_decl(html, name)
    assert b is not None, f"함수를 찾지 못했다: {name}"
    return b


def _source_of(body: str, pos: int) -> str:
    """`.slice(` 바로 앞의 단순 식별자 체인(`a.b.c`)을 뒤에서부터 잡는다.
    체인 앞이 `)`(연쇄 호출 결과, 예: `[...x].sort().slice(...)`)면 단순
    식이 아니므로 빈 문자열을 돌려준다 — 이때는 식별자 짝을 맞출 수 없어
    `_slice_paired`가 더 약한 규칙(모양만)으로 대체한다.
    """
    m = re.search(r"([\w.]+)$", body[:pos])
    return m.group(1) if m else ""


def _is_split_pair(body: str, bound: str) -> bool:
    if not re.match(r"^[A-Za-z_]\w*$", bound):
        return False
    return bool(re.search(r"\.slice\(\s*" + re.escape(bound) + r"\s*\)", body))


def _slice_paired(body: str, source: str, bound: str) -> bool:
    """이 슬라이스가 절단 고지와 실제로 짝지어지는지 본다(지적 ①-b)."""
    src_len_tok = re.escape(source) + r"\.length" if source else None
    bound_is_ident = bool(re.match(r"^[A-Za-z_]\w*$", bound))
    bound_tok = re.escape(bound) if bound_is_ident else None
    for nm in _NOTICE_RE.finditer(body):
        near = body[max(0, nm.start() - 100): nm.end() + 100]
        if src_len_tok and re.search(src_len_tok, near):
            return True
        if bound_tok and re.search(r"\b" + bound_tok + r"\b", near):
            return True
        if not source and not bound_is_ident:
            # 원본식이 복잡해 식별자 짝을 못 만든다 — ①-a로 좁힌 진짜
            # 모양의 고지가 함수 어딘가에라도 있으면 인정한다.
            return True
    if source and re.search(src_len_tok + r"\s*[,)]", body):
        # 게이트류 폴백 — 자기 본문에 고지가 없어도, 이미 다른 곳에서
        # 잠근 렌더 함수에 원본 길이를 인자로 그대로 넘기면(그 렌더
        # 함수가 화면에서 고지를 낸다) 인정한다. 호출부를 따라가 그 렌더
        # 함수 본문을 확인하지는 않는다 — 인자 전달 여부만 본다.
        return True
    return False


def _layer4_violations(html: str) -> dict:
    violations = {}
    for fn in _all_render_load_funcs(html):
        body = _cut_render_func(html, fn)
        bad = []
        for m in _SLICE_RE.finditer(body):
            bound = m.group(1) or m.group(2)
            source = _source_of(body, m.start())
            if _is_split_pair(body, bound):
                continue
            if not _slice_paired(body, source, bound):
                bad.append(m.group(0))
        if bad:
            violations[fn] = bad
    return violations


# ── 원장(ledger) — 알려진 절단 ──────────────────────────────────────────
#
# **PR-N4가 다섯 곳을 전부 고쳐 이 원장은 비었다.** 상한 값은 하나도 바꾸지
# 않았고 고지만 붙였다 — `loadHoldings`(보고자 5명·각 최근 10건),
# `loadFundDiversionGate`(후보 N건 중 최근 3건만 원문 확인 + 잘린 개수를
# 전체처럼 찍던 `acquisitionFactsHTML`의 「취득 ${results.length}건」을
# 「원문을 확인한 N건」으로), `loadAuditOpinions`(조회 범위가 최근 3개
# 사업연도라는 사실), `renderFeed`(피드 200행 상한 — 스캔 전체 절단
# 안내와는 별개 사실), `mezzanineBlockHTML`(문자열 값 절단 2곳 →
# 「…외 N자」).
#
# 비어 있는 것이 정상이다. 새 절단이 생기면 아래 집합 동등 검사가 걸린다 —
# 그때 고지를 붙이지 않고 여기에 이름만 적어 넘기지 말 것.
_LAYER4_KNOWN_GAPS = {}


def test_층4_slice_옆에_절단_고지가_있다():
    html = _html()
    funcs = _all_render_load_funcs(html)
    assert funcs, "render/HTML 계열 함수를 하나도 못 찾았다 — 정규식이 낡았다"
    violations = _layer4_violations(html)
    # 알려진 원장(다섯) 외에 새 절단이 생기면 여기서 걸린다.
    assert set(violations) == set(_LAYER4_KNOWN_GAPS), (
        f"절단 고지가 없는 함수 목록이 알려진 원장과 다르다: {violations}")


def test_층4_loadHoldings_slice에도_절단_고지가_생겼다():
    body = _cut(_html(), "loadHoldings")
    assert _SLICE_RE.search(body), "이 함수에 더 이상 slice가 없다 — xfail 자체를 지워야 한다"
    assert _NOTICE_RE.search(body), (
        "loadHoldings의 slice 옆에 절단 고지가 아직 없다(PR-N4 대상)")


@pytest.mark.parametrize(
    "fn", sorted(set(_LAYER4_KNOWN_GAPS) - {"loadHoldings"}))
def test_층4_원장_항목은_아직_고지가_없다(fn):
    """xfail로 만들지 않은 넷 — "결함 정확히 둘"이라는 이 과제의 지시를
    지키기 위해 xfail 목록에 얹지 않고, 사실 자체를 회귀로 고정한다(그
    함수가 실제로 고쳐지면 여기서 걸려 원장에서 빼라고 알려준다).
    """
    html = _html()
    assert fn in _layer4_violations(html), (
        f"{fn}에 절단 고지가 생겼다 — _LAYER4_KNOWN_GAPS에서 빼도 된다")


# ══════════════════════════════════════════════════════════════════════════
# PR-N1 결함 xfail은 더 이상 없다 — 고쳐진 상태의 잠금은 위 F 전수 절의
# `test_F_loadDeepBlocks_catch_8곳이_fetchFailHTML을_탄다`가 이어받는다.
# (옛 `test_loadDeepBlocks_catch가_부재아님을_말한다`는 그 테스트로 흡수됐다
# — `_loaddeepblocks_echo_catches()`에 의존했는데 그 헬퍼 자체가 "옛
# 리터럴이 있는 catch"라는, PR-N1 이후로는 항상 빈 집합을 돌려주는 개념이라
# 별도로 남겨 둘 이유가 없었다.)
# ══════════════════════════════════════════════════════════════════════════
# 측정 보조 — 고지 총량 상한
# ══════════════════════════════════════════════════════════════════════════

def _notice_chars(html_source: str) -> int:
    """※·⚠ 마커가 들어간 문자열 리터럴(백틱 템플릿·큰따옴표 문자열)의 총
    글자 수 + `.dim`/`.factwarn`/`.mnote` 클래스가 붙은 조각의 바로 뒤
    텍스트 글자 수를 더한 **소스 기준 근사치**다. 정확한 렌더 결과 글자
    수가 아니라 소스 안의 고지 분량이 늘어나는지 줄어드는지를 보는
    상한선이다 — 다음 PR들이 이 값을 낮춰야 한다.
    """
    total = 0
    for m in re.finditer(r"`([^`]*)`", html_source, re.S):
        s = m.group(1)
        if "※" in s or "⚠" in s:
            total += len(s)
    for m in re.finditer(r'"([^"\n]*)"', html_source):
        s = m.group(1)
        if "※" in s or "⚠" in s:
            total += len(s)
    for cls in ("dim", "factwarn", "mnote"):
        for m in re.finditer(r'class="' + cls + r'"[^>]*>([^<]*)', html_source):
            total += len(m.group(1))
    return total


# ⚠ 리뷰 지적(Critical) — 여기서 `_notice_chars(_html())`로 상한을 다시
# 재면 "검사 대상 파일에서 잰 값과 검사 대상 파일에서 잰 값"을 비교하는
# 것이라 **절대 실패할 수 없다**(파일이 아무리 늘어나도 상한도 같이
# 늘어난다). 상한은 이 커밋 시점에 손으로 측정해 **리터럴로 박는다** —
# PR-N1~N4가 이 값을 내린다 · 올라가면 실패.
_NOTICE_CHARS_CEILING = 8276  # PR-N4 완료 시점 재기준(8302→8276) — 이후 고지 추가는 이 값을 넘지 못한다


def test_고지_총량_상한():
    assert _notice_chars(_html()) <= _NOTICE_CHARS_CEILING
