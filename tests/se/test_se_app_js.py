"""app.js 순수 함수 검증 — node 서브프로세스로 실제 실행한다.

브라우저 로직을 테스트 밖에 두면 이 저장소의 유일한 품질 장치인 pytest가
닿지 않는다. app.js는 DOM도 네트워크도 만지지 않는 순수 함수만 담으므로
node로 그대로 부를 수 있다.
"""
import json
import pathlib
import re
import shutil
import subprocess
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_APP = _ROOT / "docs" / "tool" / "se" / "app.js"
_UI = _ROOT / "docs" / "tool" / "se" / "ui.js"
_NODE = shutil.which("node")


def run_js(expression: str):
    """app.js를 로드해 표현식을 평가하고 결과를 JSON으로 받는다."""
    # export를 전역에 통째로 얹는다. 고정 목록을 두면 함수가 늘 때마다
    # 목록을 고쳐야 하고, 빠뜨리면 "정의되지 않음"으로 엉뚱하게 실패한다.
    script = (
        f"Object.assign(globalThis, require({json.dumps(str(_APP))}));\n"
        f"process.stdout.write(JSON.stringify({expression}));\n"
    )
    # encoding을 명시하지 않으면 Windows에서 로케일 기본 인코딩(cp949 등)으로
    # 디코딩을 시도한다. node는 stdout에 UTF-8 바이트를 쓰므로(한글 문구가
    # 여기 섞여 있다 — pollDecision의 reason, SECTION_GROUPS의 제목 등),
    # 로케일이 다르면 UnicodeDecodeError가 나거나 운 좋게 우연히 다른 문자로
    # 잘못 디코딩될 수 있다.
    out = subprocess.run(
        [_NODE, "-e", script], capture_output=True, text=True, encoding="utf-8"
    )
    if out.returncode != 0:
        raise AssertionError(f"node 실행 실패:\n{out.stderr}")
    return json.loads(out.stdout)


# ── 공시 원문 패널 클릭 배선 재현용 가짜 DOM ────────────────────────────
#
# ui.js는 순수 함수가 아니다(document를 직접 만진다) — 그래서 위 run_js
# (app.js만 require)로는 tableEl()의 실제 클릭 경로를 검증할 수 없다.
# index.html이 app.js·ui.js를 각각 <script> 태그로 실어(모듈이 아니라
# 전역 스코프를 공유) 실행하는 것과 같은 조건을 node vm으로 재현한다 —
# 두 파일을 같은 vm 컨텍스트에서 순서대로 실행하면, ui.js가 참조하는
# app.js의 top-level const/function(예: tableLayout, AMOUNT_FIELDS)이
# 브라우저와 동일하게 전역에서 보인다.
#
# HTMLTableElement API(createTHead/createTBody/insertRow/insertCell)만
# 최소한으로 흉내 낸 가짜 엘리먼트를 쓴다 — tableEl()이 실제로 쓰는
# DOM 표면만 구현하면 충분하다.
_DOC_CLICK_HARNESS = r"""
const vm = require("vm");
const fs = require("fs");

class FakeEl {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this._text = "";
    this._className = "";
    this._listeners = {};
  }
  appendChild(c) { this.children.push(c); return c; }
  insertRow() { const tr = new FakeEl("tr"); this.appendChild(tr); return tr; }
  insertCell() { const td = new FakeEl("td"); this.appendChild(td); return td; }
  createTHead() { const el = new FakeEl("thead"); this.appendChild(el); return el; }
  createTBody() { const el = new FakeEl("tbody"); this.appendChild(el); return el; }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  dispatch(type) { (this._listeners[type] || []).forEach(function (fn) { fn({}); }); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text; }
  set className(v) { this._className = v; }
  get className() { return this._className; }
}

function collectDocEls(node, out) {
  out = out || [];
  if (!node) return out;
  if (node.className === "doc") out.push(node);
  (node.children || []).forEach(function (c) { collectDocEls(c, out); });
  return out;
}

function collectCells(node, out) {
  out = out || [];
  if (!node) return out;
  if (node.tag === "td") out.push({ text: node.textContent, title: node.title || null });
  (node.children || []).forEach(function (c) { collectCells(c, out); });
  return out;
}

const sandbox = {
  console: console,
  document: {
    createElement: function (tag) { return new FakeEl(tag); },
    createDocumentFragment: function () { return new FakeEl("#fragment"); },
    createTextNode: function (t) { const n = new FakeEl("#text"); n.textContent = t; return n; },
    addEventListener: function () {},
    getElementById: function () { return null; },
  },
  localStorage: {
    getItem: function () { return null; },
    setItem: function () {},
    removeItem: function () {},
  },
  fetch: function () { return Promise.reject(new Error("no network in test")); },
};
vm.createContext(sandbox);
// node -e "script" arg1 arg2 는 argv를 [node실행파일, arg1, arg2]로 채운다
// ("eval" 자리표시자가 없다 — node -e "console.log(process.argv)" a b로
// 직접 확인함). 그래서 인덱스가 1·2다(스크립트 파일을 직접 실행할 때의
// 2·3과 다르다).
new vm.Script(fs.readFileSync(process.argv[1], "utf-8"), { filename: "app.js" }).runInContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[2], "utf-8"), { filename: "ui.js" }).runInContext(sandbox);

// ui.js가 정의한 실제 openDocPanel을 캡처용으로 바꿔치기한다 — tableEl()
// 안의 호출은 이름으로 전역을 다시 찾아가므로(클로저로 미리 굳지 않는다),
// 스크립트 실행 뒤에 덮어써도 클릭 시점에는 이 스파이가 불린다.
const CAPTURED = [];
sandbox.openDocPanel = function (rceptNo) { CAPTURED.push(rceptNo); };

const records = %(records)s;
const table = sandbox.tableLayout(records);
const frag = table ? sandbox.tableEl(table) : null;
const docEls = frag ? collectDocEls(frag, []) : [];
docEls.forEach(function (e) { e.dispatch("click"); });

process.stdout.write(JSON.stringify({
  orientation: table ? table.orientation : null,
  caption: table ? table.caption : null,
  docTexts: docEls.map(function (e) { return e.textContent; }),
  captured: CAPTURED,
  cells: frag ? collectCells(frag, []) : [],
}));
"""


def run_doc_click(records_js: str):
    """records_js(레코드 배열 JS 리터럴)를 tableLayout → tableEl로 그린 뒤,
    class="doc"인 모든 엘리먼트를 실제로 클릭해(이벤트 리스너를 호출해)
    openDocPanel이 어떤 인자로 몇 번 불렸는지를 돌려준다.

    문자열 존재 검사(예: 소스에 "openDocPanel(" 이 있는지)가 아니라, 표를
    실제로 렌더링하고 실제 클릭 이벤트를 발생시켜 그 결과를 확인한다 —
    "가로에서는 rcept_no 열이 있지만 캡션으로 승격되면 클릭 경로 자체가
    사라진다" 같은 배선 유실은 문자열 검사로는 못 잡는다(이번에 실제로
    그렇게 통과해버린 사고였다).
    """
    script = _DOC_CLICK_HARNESS % {"records": records_js}
    out = subprocess.run(
        [_NODE, "-e", script, str(_APP), str(_UI)],
        capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode != 0:
        raise AssertionError(f"node 실행 실패:\n{out.stderr}")
    return json.loads(out.stdout)


# ── renderSection(key, value) 실제 진입점 재현용 가짜 DOM ──────────────
#
# 위 _DOC_CLICK_HARNESS는 tableLayout → tableEl까지만 재현한다(그 아래
# 계층). renderSection은 그 위에서 sectionHolder/groupHolder를 거치며
# document.getElementById로 기존 노드를 찾고 body.insertBefore로 그룹을
# 끼워 넣는다 — id 레지스트리와 insertBefore·dataset을 갖춘 가짜 DOM이
# 따로 필요하다.
_RENDER_SECTION_HARNESS = r"""
const vm = require("vm");
const fs = require("fs");

const ELEMENTS = Object.create(null);

class FakeEl {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this._text = "";
    this._className = "";
    this._id = "";
    this.dataset = {};
    this._listeners = {};
  }
  appendChild(c) { this.children.push(c); return c; }
  insertBefore(node, ref) {
    const idx = ref ? this.children.indexOf(ref) : -1;
    if (idx === -1) this.children.push(node);
    else this.children.splice(idx, 0, node);
    return node;
  }
  removeChild(c) {
    const idx = this.children.indexOf(c);
    if (idx !== -1) this.children.splice(idx, 1);
    return c;
  }
  insertRow() { const tr = new FakeEl("tr"); this.appendChild(tr); return tr; }
  insertCell() { const td = new FakeEl("td"); this.appendChild(td); return td; }
  createTHead() { const el = new FakeEl("thead"); this.appendChild(el); return el; }
  createTBody() { const el = new FakeEl("tbody"); this.appendChild(el); return el; }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  dispatch(type) { (this._listeners[type] || []).forEach(function (fn) { fn({}); }); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text; }
  set className(v) { this._className = v; }
  get className() { return this._className; }
  set id(v) { this._id = v; ELEMENTS[v] = this; }
  get id() { return this._id; }
}

const bodyEl = new FakeEl("div");
bodyEl.id = "body";

function collectCells(node, out) {
  out = out || [];
  if (!node) return out;
  if (node.tag === "td" || node.tag === "th") out.push(node.textContent);
  (node.children || []).forEach(function (c) { collectCells(c, out); });
  return out;
}

function collectTitles(node, out) {
  out = out || [];
  if (!node) return out;
  if (node.tag === "h3") out.push(node.textContent);
  (node.children || []).forEach(function (c) { collectTitles(c, out); });
  return out;
}

// fund_usage 안내문(renderSection이 holder에 직접 붙이는 <p class="note">)
// 처럼 표가 아닌 문단이 실제로 DOM에 그려지는지 확인하기 위한 수집기 —
// collectTitles(h3)와 같은 방식이다. blockEl()이 데이터 없음 안내에도
// 같은 className("note")을 쓰므로, 특정 섹션 전용 문구인지는 텍스트
// 내용으로 호출부에서 구분한다.
function collectNotes(node, out) {
  out = out || [];
  if (!node) return out;
  if (node.tag === "p" && node.className === "note") out.push(node.textContent);
  (node.children || []).forEach(function (c) { collectNotes(c, out); });
  return out;
}

const sandbox = {
  console: console,
  document: {
    createElement: function (tag) { return new FakeEl(tag); },
    createDocumentFragment: function () { return new FakeEl("#fragment"); },
    createTextNode: function (t) { const n = new FakeEl("#text"); n.textContent = t; return n; },
    addEventListener: function () {},
    getElementById: function (id) { return ELEMENTS[id] || null; },
  },
  localStorage: {
    getItem: function () { return null; },
    setItem: function () {},
    removeItem: function () {},
  },
  fetch: function () { return Promise.reject(new Error("no network in test")); },
};
vm.createContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[1], "utf-8"), { filename: "app.js" }).runInContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[2], "utf-8"), { filename: "ui.js" }).runInContext(sandbox);

sandbox.openDocPanel = function () {};
sandbox.renderSection(%(key)s, %(value)s);

process.stdout.write(JSON.stringify({
  cells: collectCells(bodyEl, []),
  titles: collectTitles(bodyEl, []),
  notes: collectNotes(bodyEl, []),
}));
"""


def run_render_section(key_js: str, value_js: str):
    """renderSection(key, value)을 실제로 호출해(app.js·ui.js를 같은 vm
    컨텍스트에서 순서대로 실행) 결과 DOM에서 표 셀 텍스트와 소제목(h3)
    텍스트를 모은다. sectionBlocks 단독 호출(위 클래스들)로는 못 잡는,
    ui.js 호출부 자체의 배선 누락(key 전달 누락)을 잡기 위한 것이다.
    """
    script = _RENDER_SECTION_HARNESS % {"key": key_js, "value": value_js}
    out = subprocess.run(
        [_NODE, "-e", script, str(_APP), str(_UI)],
        capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode != 0:
        raise AssertionError(f"node 실행 실패:\n{out.stderr}")
    return json.loads(out.stdout)


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestNextKeysToFetch(unittest.TestCase):
    def test_returns_keys_not_yet_fetched(self):
        got = run_js('nextKeysToFetch(["a","b","c"], ["a"])')
        self.assertEqual(got, ["b", "c"])

    def test_returns_empty_when_all_fetched(self):
        self.assertEqual(run_js('nextKeysToFetch(["a","b"], ["a","b"])'), [])

    def test_never_refetches_across_polls(self):
        """폴링이 반복돼도 같은 키를 두 번 주지 않아야 한다.

        SE-4a가 없앤 737KB 문제가 되돌아오는 경로가 정확히 여기다.
        """
        got = run_js(
            '(() => { const seen=[]; let out=[];'
            ' for (const poll of [["a"],["a","b"],["a","b","c"]]) {'
            '   const n = nextKeysToFetch(poll, seen); out = out.concat(n);'
            '   for (const k of n) seen.push(k); }'
            ' return out; })()'
        )
        self.assertEqual(got, ["a", "b", "c"], "같은 섹션을 다시 받고 있습니다")

    def test_ignores_unknown_extra_keys_in_fetched(self):
        self.assertEqual(run_js('nextKeysToFetch(["a"], ["zzz"])'), ["a"])


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestPollDecision(unittest.TestCase):
    def test_stops_when_done(self):
        got = run_js('pollDecision({done: true, stalled: false, processed: 3})')
        self.assertTrue(got["shouldStop"])

    def test_stops_when_stalled(self):
        """진행이 멈췄는데 계속 부르면 DART 호출 한도만 태운다."""
        got = run_js('pollDecision({done: false, stalled: true, processed: 0})')
        self.assertTrue(got["shouldStop"])
        self.assertTrue(got["reason"], "멈춘 이유를 사용자에게 말해야 합니다")

    def test_continues_while_progressing(self):
        got = run_js('pollDecision({done: false, stalled: false, processed: 2})')
        self.assertFalse(got["shouldStop"])

    def test_missing_fields_do_not_loop_forever(self):
        """응답이 예상과 달라도 무한 루프에 빠지면 안 된다."""
        got = run_js("pollDecision({})")
        self.assertTrue(got["shouldStop"])

    def test_surfaces_server_error_message_instead_of_generic_fallback(self):
        """step 응답이 {error: "X-DART-Key 헤더가 필요합니다"} 같은 curated
        문구를 주면(se_server/api/types.py Response.error), 사용자가 스스로
        고칠 수 있는 오류인데 "서버 응답을 이해하지 못했습니다"로 뭉개면
        안 된다.
        """
        got = run_js(
            'pollDecision({error: "X-DART-Key 헤더가 필요합니다"})'
        )
        self.assertTrue(got["shouldStop"])
        self.assertEqual(got["reason"], "X-DART-Key 헤더가 필요합니다")

    def test_generic_fallback_still_used_when_no_error_field(self):
        """error 필드 자체가 없는, 정말 예상 밖인 응답에서는 여전히 폴백
        문구를 써야 한다 — 이 테스트가 깨지면 폴백 경로가 사라진 것이다.
        """
        got = run_js('pollDecision({foo: "bar"})')
        self.assertTrue(got["shouldStop"])
        self.assertEqual(got["reason"], "서버 응답을 이해하지 못했습니다.")


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestSectionGroups(unittest.TestCase):
    def test_covers_all_stage1_keys_except_header(self):
        """registry의 1단 키 13개가 화면 어딘가에는 나와야 한다.

        빠지면 데이터를 받아놓고 보여주지 않는 것이다.
        """
        from se_server.jobs.registry import STAGE1_SPECS

        groups = run_js("SECTION_GROUPS")
        shown = {k for g in groups for k in g["keys"]}
        # doc_list는 STAGE1_SPECS에 없는 2단 합성 키(개별 doc:<접수번호>
        # 섹션들을 addDocListEntry가 목록 하나로 모은 것, DOC_LIST_KEY
        # 참고)다 — 화면에는 나와야 하므로 SECTION_GROUPS에 있지만, 이
        # 검사는 "1단 API 키가 전부 어딘가에 나오는가"만 보므로 따로 뺀다.
        shown_stage1 = shown - {"doc_list"}
        expected = {s.key for s in STAGE1_SPECS} - {"company_info"}  # 헤더는 별도
        self.assertEqual(expected - shown_stage1, set(),
                         "화면에 안 나오는 섹션이 있습니다")
        self.assertEqual(shown_stage1 - expected, set(),
                         "registry에 없는 섹션 키를 그리려 합니다")


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestStage1KeysHaveLabels(unittest.TestCase):
    def test_every_stage1_key_has_a_label(self):
        """company_info처럼 라벨이 빠지면 화면에 영문 키가 그대로 뜨고
        groupTitleFor가 "기타" 그룹으로 밀어낸다 — 13개 1단 섹션 키 전부가
        LABELS에 있어야 한다(company_info는 헤더라 SECTION_GROUPS에는
        없지만 label()은 여전히 거쳐야 한다).
        """
        from se_server.jobs.registry import STAGE1_SPECS

        labels = run_js("LABELS")
        missing = [s.key for s in STAGE1_SPECS if s.key not in labels]
        self.assertEqual(missing, [], f"라벨이 없는 1단 섹션 키: {missing}")


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestToRecords(unittest.TestCase):
    """toTable을 지우면서(사용처가 없는 죽은 함수였다 — 대체한 tableLayout이
    실제로 화면을 그린다) toRecords 자체의 정규화 계약은 이 클래스가 직접
    검증한다. "표로 만들 근거가 없을 때만 null, 스칼라·리스트는 감싸서
    보존" 원칙은 toRecords가 여전히 지켜야 한다 — sectionBlocks가 그대로
    의존한다.
    """

    def test_empty_value_is_null(self):
        for expr in ("toRecords([])", "toRecords(null)", "toRecords(undefined)"):
            self.assertIsNone(run_js(expr), f"{expr}가 레코드를 만들었습니다")

    def test_empty_dict_becomes_one_field_less_record_not_null(self):
        """toRecords({})는 null이 아니라 [{}]다 — "표로 만들 근거가
        없다"(빈 키)는 판정은 이 함수의 몫이 아니라 그 위(tableLayout의
        `keys.length === 0` 가드)의 몫이다. toRecords는 그저 감싸기만
        한다."""
        self.assertEqual(run_js('toRecords({})'), [{}])
        self.assertIsNone(run_js('tableLayout(toRecords({}))'),
                          "빈 객체는 tableLayout 단계에서 표로 만들 근거가 "
                          "없어야 합니다")

    def test_single_dict_becomes_one_record(self):
        self.assertEqual(run_js('toRecords({a:1})'), [{"a": 1}])

    def test_scalar_string_value_is_wrapped_not_dropped(self):
        """toRecords("문자열")이 null이면 화면은 "표시할 데이터가
        없습니다"라고 말한다 — 데이터가 있는데 없다고 하는 것이다."""
        self.assertEqual(run_js('toRecords("어떤 문자열")'), [{"값": "어떤 문자열"}])

    def test_list_of_scalars_is_wrapped_item_by_item(self):
        self.assertEqual(run_js('toRecords(["a","b"])'), [{"값": "a"}, {"값": "b"}])

    def test_non_object_list_items_are_wrapped_not_dropped(self):
        got = run_js('toRecords([{a:1},"note",{b:2}])')
        self.assertEqual(got, [{"a": 1}, {"값": "note"}, {"b": 2}])


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestTableLayoutPreservesData(unittest.TestCase):
    """toTable을 지우면서 그 계약(모르는 필드를 숨기지 않는다·0과 false를
    잃지 않는다·중첩 객체가 사라지지 않는다·프로토타입 키가 열을 오염시키지
    않는다)을 tableLayout 기준으로 이식한다 — toTable은 프로덕션 소비처가
    0개인 죽은 함수였고, 그 성질을 실제로 화면을 그리는 tableLayout이
    지켜야 의미가 있다(리뷰 지적 ③).

    아래 테스트는 모두 레코드 2건 이상을 써서 가로(horizontal) 경로를
    탄다 — 1건은 세로로 빠져 columns/caption 승격 로직 자체를 타지 않는다.
    """

    def test_columns_union_covers_ragged_records(self):
        """레코드마다 필드가 다를 수 있다. 어느 것도 사라지면 안 된다."""
        got = run_js('tableLayout([{a:1},{b:2}])')
        self.assertEqual(sorted(got["keys"]), ["a", "b"])

    def test_unknown_field_keeps_raw_key_in_keys_and_columns(self):
        """라벨이 없다고 열을 숨기면 데이터가 조용히 사라진다."""
        got = run_js('tableLayout([{wholly_unknown_field:"x"},{wholly_unknown_field:"y"}])')
        self.assertIn("wholly_unknown_field", got["keys"])
        self.assertIn("wholly_unknown_field", got["columns"])

    def test_keys_carry_raw_field_names_in_column_order(self):
        """columns는 한국어 라벨(사람이 읽는 값)이고, keys는 라벨링 이전의
        원본 필드명이어야 한다 — ui.js의 tableEl()이 "이 열이 rcept_no인가"를
        라벨("접수번호")로 추측하지 않고 keys로 정확히 찾기 때문이다(TestDocPanelClickWiring
        참고 — 실제 클릭 경로로 다시 확인한다).
        """
        got = run_js(
            'tableLayout([{rcept_dt:"20240301",rcept_no:"20240301000001"},'
            ' {rcept_dt:"20240302",rcept_no:"20240301000002"}])'
        )
        self.assertEqual(got["keys"], ["rcept_dt", "rcept_no"])
        self.assertEqual(got["columns"], ["접수일자", "접수번호"])

    def test_nested_value_is_stringified_not_dropped(self):
        got = run_js('tableLayout([{x:{deep:1}},{x:{deep:2}}])')
        flat = [c for r in got["rows"] for c in r]
        self.assertTrue(any("deep" in c for c in flat), "중첩 객체가 사라졌습니다")

    def test_null_cell_becomes_empty_string_not_the_word_null(self):
        got = run_js('tableLayout([{a:null},{a:1}])')
        flat = [c for r in got["rows"] for c in r]
        self.assertIn("", flat)
        self.assertNotIn("null", flat)

    def test_zero_and_false_are_not_blanked(self):
        """0과 false는 '없음'이 아니라 유효한 값이다."""
        got = run_js('tableLayout([{a:0,b:false},{a:1,b:true}])')
        flat = [c for r in got["rows"] for c in r]
        self.assertIn("0", flat)
        self.assertIn("false", flat)

    def test_non_object_list_items_are_not_dropped(self):
        """리스트 안 비객체 항목(문자열 등)이 흔적 없이 사라지면 안 된다 —
        toRecords로 미리 감싸지 않고 tableLayout에 배열을 바로 넘겨도
        (④ 수정: 방어가 호출부가 아니라 tableLayout 자신의 계약이다)
        살아남아야 한다.
        """
        got = run_js('tableLayout([{a:1},"note",{a:2}])')
        self.assertEqual(len(got["rows"]), 3, "비객체 항목이 사라졌습니다")
        flat = [c for r in got["rows"] for c in r]
        self.assertIn("note", flat, "문자열 항목의 내용이 화면 어디에도 없습니다")

    def test_label_lookup_ignores_prototype_keys(self):
        """LABELS가 프로토타입이 있는 일반 객체면 "toString"·"constructor"
        같은 키가 Object.prototype 메서드로 새어나간다 — 컬럼 헤더가 함수
        객체가 되고(JSON 직렬화 시 배열 안 함수는 null이 된다), 실제로
        확인된 버그다.
        """
        got = run_js(
            'tableLayout([{toString:"x",constructor:"y"},{toString:"a",constructor:"b"}])'
        )
        self.assertIn("toString", got["columns"])
        self.assertIn("constructor", got["columns"])
        self.assertNotIn(None, got["columns"], "헤더가 함수로 새어나갔습니다")

    def test_raw_amount_value_is_carried_alongside_the_formatted_value(self):
        """AMOUNT_FIELDS(app.js)는 억·조 단위로 줄여 보여준다(예:
        1,308,239,417 → "13.1억") — ui.js가 title(마우스 오버)로 정확한
        원 단위 값을 보여주려면(리뷰 지적 ⑤) raw가 표시값과 나란히 있어야
        한다.
        """
        got = run_js('tableLayout([{plan_amount:1308239417},{plan_amount:1}])')
        flat_raw = [c for r in got["raw"] for c in r]
        self.assertIn("1308239417", flat_raw)

    def test_vertical_raw_is_a_flat_array_indexed_like_keys(self):
        """세로는 레코드 1건이라 raw도 rows처럼 2차원이 아니라 keys와 같은
        길이의 1차원 배열이다 — ui.js가 orientation으로 분기해 인덱싱한다.
        """
        got = run_js('tableLayout([{plan_amount:1308239417}])')
        idx = got["keys"].index("plan_amount")
        self.assertEqual(got["raw"][idx], "1308239417")


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestReprtCodeLabels(unittest.TestCase):
    """reprt_code(11011 등) 내부 코드를 사람이 읽는 한국어로 바꾸는
    REPRT_CODE_LABELS 검증. 내부 함수(formatValue 안의 변환 분기)는
    export되지 않으므로 실제 진입점인 formatValue·tableLayout으로
    검증한다.

    확인 대상: 네 코드(11011/11012/11013/11014) 전부가 변환되는지, 모르는
    코드는 원본을 그대로 두는지("데이터를 숨기지 않는다" — label()과 같은
    계약), 코드처럼 생긴 다른 필드 값(예: 접수번호)이 reprt_code가 아닌
    필드에 있을 때 잘못 변환되지 않는지.
    """

    def test_all_four_known_codes_convert(self):
        expected = {
            "11011": "사업보고서", "11012": "반기보고서",
            "11013": "1분기보고서", "11014": "3분기보고서",
        }
        for code, label_ko in expected.items():
            got = run_js(f'formatValue("reprt_code", "{code}")')
            self.assertEqual(got, label_ko, f"reprt_code {code}가 변환되지 않았습니다")

    def test_numeric_report_code_value_also_converts(self):
        """field-inventory 실측(financials.reprt_code 등)은 문자열이 아니라
        숫자 타입("숫자")이다 — JSON에서 숫자로 오는 실제 형태도
        변환돼야 한다."""
        got = run_js('formatValue("reprt_code", 11011)')
        self.assertEqual(got, "사업보고서")

    def test_unknown_report_code_is_shown_as_is(self):
        """예상 밖 코드를 숨기면 안 된다 — "모르면 원본 그대로"가 label()과
        동일한 계약이라는 것이 REPRT_CODE_LABELS 주석의 명시적 근거다."""
        got = run_js('formatValue("reprt_code", "99999")')
        self.assertEqual(got, "99999")

    def test_code_like_value_under_a_different_key_is_not_converted(self):
        """이 변환은 필드 **이름**(key==="reprt_code")에 묶여 있어야 한다 —
        우연히 같은 문자열 값을 가진 다른 필드(접수번호·사업연도 등)까지
        같이 바뀌면 안 된다."""
        self.assertEqual(run_js('formatValue("rcept_no", "11011")'), "11011")
        self.assertEqual(run_js('formatValue("bsns_year", "11012")'), "11012")

    def test_wired_through_table_layout_for_a_constant_column(self):
        """financials 실측(field-inventory: reprt_code가 constant_columns에
        있다)처럼 여러 행에서 값이 같아 캡션으로 승격되는 경로에서도
        변환이 적용돼야 한다."""
        got = run_js(
            'tableLayout([{reprt_code:"11011",account_nm:"유동자산"},'
            ' {reprt_code:"11011",account_nm:"비유동자산"}])'
        )
        caption_values = {c["key"]: c["value"] for c in got["caption"]}
        self.assertEqual(caption_values.get("reprt_code"), "사업보고서",
                          "캡션으로 승격된 reprt_code가 변환되지 않았습니다")

    def test_wired_through_table_layout_when_it_varies_by_row(self):
        """fund_usage처럼 회차마다 분기 보고서가 다를 수 있는 가로 표에서는
        열 본문(캡션이 아니라)에 남는다 — 각 행의 값이 올바르게 변환돼야
        한다."""
        got = run_js(
            'tableLayout([{reprt_code:"11011",tm:"제1회"},'
            ' {reprt_code:"11013",tm:"제1회"}])'
        )
        self.assertIn("reprt_code", got["keys"], "reprt_code가 본문 열에 남아있지 않습니다")
        idx = got["keys"].index("reprt_code")
        cells = [row[idx] for row in got["rows"]]
        self.assertIn("사업보고서", cells)
        self.assertIn("1분기보고서", cells)


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestTableLayout(unittest.TestCase):
    """세로/가로 자동 판단 + 상수열 캡션 승격.

    tableLayout이 toTable을 대체해 sectionBlocks가 실제로 그리는 표를
    만든다 — 1건짜리 레코드(indicators 49열)는 세로로, N건(disclosures
    145건)은 가로로 그리고, 가로에서 모든 행이 같은 값인 열(corp_name 등)은
    표 위 캡션으로 올려 145줄 반복을 없앤다.
    """

    def test_single_record_is_vertical(self):
        got = run_js('tableLayout([{a:1,b:2,c:3}])')
        self.assertEqual(got["orientation"], "vertical")

    def test_many_records_is_horizontal(self):
        got = run_js('tableLayout([{a:1},{a:2},{a:3}])')
        self.assertEqual(got["orientation"], "horizontal")

    def test_constant_columns_move_to_caption(self):
        got = run_js('tableLayout([{co:"엔켐",n:1},{co:"엔켐",n:2}])')
        self.assertNotIn("co", got["keys"])
        self.assertTrue(any(c["value"] == "엔켐" for c in got["caption"]))

    def test_varying_column_stays_in_table(self):
        got = run_js('tableLayout([{co:"엔켐",n:1},{co:"엔켐",n:2}])')
        self.assertIn("n", got["keys"])

    def test_single_record_has_no_caption_promotion(self):
        """1건일 때 모든 열이 '상수'이므로 승격하면 표가 통째로 사라진다."""
        got = run_js('tableLayout([{a:1,b:2}])')
        self.assertEqual(got["caption"], [])
        self.assertEqual(sorted(got["keys"]), ["a", "b"])

    def test_no_data_is_lost_between_caption_and_table(self):
        """어떤 열도 캡션에도 표에도 없으면 데이터가 사라진 것이다."""
        got = run_js('tableLayout([{a:"x",b:1},{a:"x",b:2}])')
        shown = set(got["keys"]) | {c["key"] for c in got["caption"]}
        self.assertEqual(shown, {"a", "b"}, "열이 사라졌습니다")

    def test_vertical_rows_are_label_value_pairs(self):
        got = run_js('tableLayout([{rcept_no:"20260724000552"}])')
        self.assertEqual(got["rows"][0][0], "접수번호")

    def test_values_are_formatted(self):
        got = run_js('tableLayout([{plan_amount:13082000000},{plan_amount:1}])')
        self.assertIn("130.8억", [c for r in got["rows"] for c in r])

    def test_empty_input_is_null(self):
        for expr in ("tableLayout([])", "tableLayout(null)"):
            self.assertIsNone(run_js(expr))


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestWideTableFolding(unittest.TestCase):
    """insider_timeline(상수열 제외 36열) 대응 — 12열을 넘으면 나머지를
    접는다. 접는 것이지 없애는 것이 아니다: 어떤 열도 keys·foldedKeys·
    caption 중 정확히 하나에는 있어야 한다.
    """

    _WIDE = "Array.from({length:3},(_,i)=>Object.fromEntries(Array.from({length:20},(_,j)=>['f'+j, i+'-'+j])))"

    def test_visible_columns_are_capped(self):
        got = run_js(f"tableLayout({self._WIDE})")
        self.assertLessEqual(len(got["keys"]), 12)

    def test_folded_columns_are_reported_not_dropped(self):
        got = run_js(f"tableLayout({self._WIDE})")
        self.assertTrue(got["foldedKeys"], "접힌 열 목록이 없습니다")

    def test_every_column_is_either_visible_folded_or_caption(self):
        got = run_js(f"tableLayout({self._WIDE})")
        accounted = set(got["keys"]) | set(got["foldedKeys"]) | {c["key"] for c in got["caption"]}
        self.assertEqual(len(accounted), 20, "열이 사라졌습니다")

    def test_narrow_table_folds_nothing(self):
        got = run_js('tableLayout([{a:1,b:2},{a:3,b:4}])')
        self.assertEqual(got["foldedKeys"], [])

    def test_folded_rows_carry_the_hidden_values(self):
        got = run_js(f"tableLayout({self._WIDE})")
        self.assertTrue(got["foldedRows"][0], "접힌 값이 비어 있습니다")

    def test_rcept_no_stays_visible_even_when_pushed_past_the_cap(self):
        """insider_timeline에는 실제로 rcept_no가 있다. ui.js는 오직
        table.keys.indexOf("rcept_no")로만 공시 원문 패널의 클릭 셀을
        찾는다 — 앞에서부터 단순히 12개만 자르면, 원본 응답에서 rcept_no가
        13번째 이후에 나타나는 경우 이 열이 접혀 패널 배선이 끊긴다
        (affiliates·financials에서 실제로 있었던 사고와 같은 부류).
        """
        wide_with_rcept_no = (
            "Array.from({length:3},(_,i)=>Object.assign("
            "Object.fromEntries(Array.from({length:20},(_,j)=>['f'+j, i+'-'+j])),"
            "{rcept_no: '2026010100000'+i}))"
        )
        got = run_js(f"tableLayout({wide_with_rcept_no})")
        self.assertIn("rcept_no", got["keys"],
                       "rcept_no가 접혀 공시 원문 패널 배선이 끊깁니다")
        self.assertNotIn("rcept_no", got["foldedKeys"])

    def test_folding_preserves_original_column_order_among_visible(self):
        """essential 승격이 열 순서를 뒤섞어 "앞 열부터"라는 사용자 기대를
        깨면 안 된다 — rcept_no를 포함하되 나머지 visible 열은 원래
        순서를 유지해야 한다."""
        wide_with_rcept_no = (
            "Array.from({length:3},(_,i)=>Object.assign("
            "Object.fromEntries(Array.from({length:20},(_,j)=>['f'+j, i+'-'+j])),"
            "{rcept_no: '2026010100000'+i}))"
        )
        got = run_js(f"tableLayout({wide_with_rcept_no})")
        non_essential_visible = [k for k in got["keys"] if k != "rcept_no"]
        self.assertEqual(non_essential_visible, sorted(non_essential_visible, key=lambda k: int(k[1:])))


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestSectionBlocks(unittest.TestCase):
    """dict-of-lists 섹션(shareholders/audit_history/debt_balance 등)을
    소제목 + 개별 표 블록 목록으로 펼치는 sectionBlocks() 검증.
    """

    def test_empty_value_yields_no_blocks(self):
        for expr in ('sectionBlocks(null)', 'sectionBlocks(undefined)', 'sectionBlocks({})'):
            self.assertEqual(run_js(expr), [], f"{expr}가 빈 블록이 아닙니다")

    def test_plain_array_becomes_single_block(self):
        got = run_js('sectionBlocks([{a:1},{a:2}])')
        self.assertEqual(len(got), 1)
        self.assertIsNone(got[0]["title"])
        self.assertEqual(len(got[0]["table"]["rows"]), 2)

    def test_flat_dict_becomes_single_block(self):
        """indicators처럼 하위 구조 없는 순수 스칼라 dict는 굳이 안 쪼갠다.

        레코드 1건이므로 세로(키-값)로 그려진다 — indicators 실측(1건
        49열)을 가로로 펴면 열 하나가 몇 픽셀이 되어 글자가 쪼개지는
        문제가 Task 2의 핵심 수정 대상이다(tableLayout).
        """
        got = run_js('sectionBlocks({순이익률: 12.3, 부채비율: 45.6})')
        self.assertEqual(len(got), 1)
        self.assertIsNone(got[0]["title"])
        self.assertEqual(got[0]["table"]["orientation"], "vertical")
        self.assertEqual(
            got[0]["table"]["rows"],
            [["순이익률", "12.3"], ["부채비율", "45.6"]],
        )

    def test_dict_of_lists_splits_into_titled_blocks(self):
        """shareholders 형태: {major_holders:[...], bulk_holders:[...]}.

        지금은 이게 한 셀에 JSON 문자열로 뭉쳐 들어간다 — 최대주주 현황을
        사람이 읽을 수 없으면 화면을 만든 의미가 없다.
        """
        got = run_js(
            'sectionBlocks({major_holders:[{nm:"a"}], bulk_holders:[{nm:"b"}]})'
        )
        self.assertEqual(len(got), 2)
        titles = [b["title"] for b in got]
        self.assertIn("최대주주", titles)
        self.assertIn("5% 대량보유", titles)
        for b in got:
            self.assertIsNotNone(b["table"], f"{b['title']} 블록에 표가 없습니다")

    def test_unlabeled_sub_key_keeps_raw_name(self):
        """라벨이 없는 하위 키는 원본 그대로 써야 한다 — 숨기지 않는다."""
        got = run_js('sectionBlocks({wholly_unknown_group:[{a:1}]})')
        self.assertEqual(got[0]["title"], "wholly_unknown_group")

    def test_mixed_flat_and_nested_keeps_both(self):
        """debt_balance 형태: 스칼라 필드(year·total 등) + 중첩 dict(by_kind).

        스칼라는 표 하나로, 중첩은 하위 키별 블록으로 — 어느 쪽도 사라지면
        안 된다.
        """
        got = run_js(
            'sectionBlocks({year:2024, total:100,'
            ' by_kind:{corporate_bond:{total:100}}})'
        )
        flat_blocks = [b for b in got if b["title"] is None]
        nested_blocks = [b for b in got if b["title"] is not None]
        self.assertEqual(len(flat_blocks), 1, "스칼라 필드(year/total)가 안 보입니다")
        self.assertTrue(
            any("종류별 잔액" in b["title"] for b in nested_blocks),
            "by_kind 블록이 안 보입니다",
        )
        self.assertTrue(
            any("회사채" in b["title"] for b in nested_blocks),
            "by_kind 하위(corporate_bond) 라벨이 안 보입니다",
        )

    def test_empty_nested_list_still_gets_its_own_block(self):
        """하위 리스트가 비어 있어도(예: independence_warnings: []) 그 사실을
        블록으로 남긴다 — 통째로 빠지면 "이 항목을 확인했는데 비어 있다"와
        "이 항목 자체가 없다"를 구분할 수 없다.
        """
        got = run_js('sectionBlocks({opinions:[], independence_warnings:[]})')
        titles = [b["title"] for b in got]
        self.assertIn("감사의견", titles)
        self.assertIn("감사인 독립성 경고", titles)

    def test_list_of_strings_inside_dict_is_not_dropped(self):
        """independence_warnings는 dict의 리스트가 아니라 **문자열**의
        리스트다. toTable의 ② 수정과 맞물려 문자열도 살아남아야 한다.
        """
        got = run_js(
            'sectionBlocks({independence_warnings:["3년 연속 재직"]})'
        )
        self.assertEqual(len(got), 1)
        flat = [cell for row in got[0]["table"]["rows"] for cell in row]
        self.assertIn("3년 연속 재직", flat)

    def test_long_text_is_not_embedded_in_a_table(self):
        """doc: 섹션의 text(최대 8000자)처럼 표 셀(max-width:280px)에 욱여넣기엔
        너무 긴 문자열은 표가 아니라 별도 text 블록으로 빠져야 한다.
        """
        long_text = "가" * 500
        got = run_js(
            'sectionBlocks({main_file:"a.html", text:' + json.dumps(long_text) + "})"
        )
        text_blocks = [b for b in got if b.get("text")]
        self.assertEqual(len(text_blocks), 1, "긴 문자열 블록이 없습니다")
        self.assertEqual(text_blocks[0]["text"], long_text, "원문이 손상됐습니다")
        for b in got:
            if b.get("table"):
                for row in b["table"]["rows"]:
                    for c in row:
                        self.assertNotIn(long_text, c, "긴 문자열이 표 셀에 욱여넣어졌습니다")


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestHiddenIdKeysOmission(unittest.TestCase):
    """corp_code·corp_cls를 company_info 밖의 모든 섹션에서 걷어내는
    omitHiddenIds(HIDDEN_ID_KEYS)의 실제 진입점(sectionBlocks)을 검증한다
    — 내부 함수 자체는 export되지 않는다.

    확인 대상: 대상 필드가 실제로 빠지는지 / company_info에서는 살아
    있는지 / 다른 필드가 같이 사라지지 않는지(가장 위험한 실패 모드 —
    데이터 유실).
    """

    def test_corp_code_and_corp_cls_are_dropped_outside_company_info(self):
        records = [
            {"corp_code": "00126380", "corp_cls": "Y", "account_nm": "유동자산", "thstrm_amount": 100},
            {"corp_code": "00126380", "corp_cls": "Y", "account_nm": "비유동자산", "thstrm_amount": 200},
        ]
        got = run_js(
            f'sectionBlocks({json.dumps(records, ensure_ascii=False)}, 0, "financials")'
        )
        table = got[0]["table"]
        present = set(table["keys"]) | {c["key"] for c in table["caption"]}
        self.assertNotIn("corp_code", present, "corp_code가 financials 섹션에서 안 걸러졌습니다")
        self.assertNotIn("corp_cls", present, "corp_cls가 financials 섹션에서 안 걸러졌습니다")

    def test_company_info_keeps_both_fields(self):
        """company_info는 이 값들이 사용자 눈에 보이는 유일한 자리다 —
        여기서까지 지우면 데이터가 화면 어디에도 남지 않는다."""
        value = {
            "corp_code": "00126380", "corp_cls": "Y",
            "corp_name": "엔켐", "ceo_nm": "오정강",
        }
        got = run_js(f'sectionBlocks({json.dumps(value, ensure_ascii=False)}, 0, "company_info")')
        table = got[0]["table"]
        self.assertEqual(table["orientation"], "vertical")
        self.assertIn("corp_code", table["keys"], "company_info에서 corp_code가 사라졌습니다")
        self.assertIn("corp_cls", table["keys"], "company_info에서 corp_cls가 사라졌습니다")

    def test_only_the_two_id_fields_are_dropped_not_neighbors(self):
        """가장 위험한 실패 모드: 다른 필드가 함께 사라지는 것. stock_code
        (종목코드)처럼 이름이 비슷하거나 나란히 오는 다른 필드는 살아남아야
        한다(field-inventory의 disclosures 실측 필드 구성)."""
        records = [
            {"corp_code": "00126380", "corp_cls": "Y", "stock_code": "348370",
             "corp_name": "엔켐", "report_nm": "[기재정정]주요사항보고서"},
            {"corp_code": "00126380", "corp_cls": "Y", "stock_code": "348370",
             "corp_name": "엔켐", "report_nm": "전환사채발행결정"},
        ]
        got = run_js(
            f'sectionBlocks({json.dumps(records, ensure_ascii=False)}, 0, "disclosures")'
        )
        table = got[0]["table"]
        present = set(table["keys"]) | {c["key"] for c in table["caption"]}
        for must_keep in ("stock_code", "corp_name", "report_nm"):
            self.assertIn(must_keep, present, f"{must_keep}가 corp_code와 함께 사라졌습니다")

    def test_dropped_recursively_from_nested_dict_of_lists(self):
        """shareholders({major_holders, bulk_holders})처럼 값이 중첩돼 있어도
        하위 리스트 안의 corp_code까지 빠져야 한다 — omitHiddenIds는 트리
        전체를 재귀적으로 훑는다(sectionBlocks 재귀 깊이가 아니라)."""
        value = {
            "major_holders": [{"corp_code": "00126380", "nm": "오정강"}],
            "bulk_holders": [{"corp_code": "00126380", "nm": "와이어트그룹"}],
        }
        got = run_js(f'sectionBlocks({json.dumps(value, ensure_ascii=False)}, 0, "shareholders")')
        for block in got:
            table = block.get("table")
            if not table:
                continue
            present = set(table["keys"]) | {c["key"] for c in table["caption"]}
            self.assertNotIn("corp_code", present,
                              f"{block['title']} 표에 corp_code가 남아 있습니다")

    def test_corp_code_does_appear_when_the_gate_is_not_applied(self):
        """대조군: 같은 데이터를 company_info로 위장해 게이트를 우회하면
        corp_code가 실제로 표에 나온다는 것을 확인해, 위 검사들이 애초에
        무언가를 검증하고 있다는 것을 보장한다(항상-초록 테스트 방지)."""
        records = [{"corp_code": "00126380", "account_nm": "유동자산"}]
        got = run_js(
            f'sectionBlocks({json.dumps(records, ensure_ascii=False)}, 0, "company_info")'
        )
        table = got[0]["table"]
        self.assertIn("corp_code", table["keys"])


def _flatten_table_cells(table):
    """세로(rows: [[label,value], ...])·가로(rows: [[v1,v2,...], ...]) 둘
    다 "행 목록의 목록"이라는 같은 모양이라, 방향을 가리지 않고 모든 셀
    문자열을 한 목록으로 편다."""
    return [c for row in table["rows"] for c in row]


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestAggregateRowSplit(unittest.TestCase):
    """최대주주 현황(shareholders.major_holders)에 섞여 오는 합계
    ("계"/"합계"/"총계") 행을 사람 목록에서 분리하는 splitAggregateRows의
    실제 진입점(sectionBlocks, key="shareholders")을 검증한다.

    확인 대상: "계" 행이 사람 목록에서 빠지는지 / 합계 자체가 사라지지
    않고 어딘가에 남는지(없애는 게 아니라 분리하는 것) / 이름이 "계"로
    시작하는 실제 인물(예: "계상훈")이 오탐되지 않는지 / 합계 행이 없는
    데이터에서도 안전한지.
    """

    _PEOPLE = [
        {"nm": "오정강", "relate": "본인", "trmend_posesn_stock_qota_rt": "17.40"},
        {"nm": "오정섭", "relate": "특수관계인", "trmend_posesn_stock_qota_rt": "2.10"},
    ]

    def _blocks_for(self, major_holders):
        value = {"major_holders": major_holders, "bulk_holders": []}
        return run_js(f'sectionBlocks({json.dumps(value, ensure_ascii=False)}, 0, "shareholders")')

    def _people_block(self, blocks):
        return next(b for b in blocks if b["title"] == "최대주주")

    def test_aggregate_row_is_removed_from_the_people_table(self):
        total_row = {"nm": "계", "relate": "-", "trmend_posesn_stock_qota_rt": "19.50"}
        got = self._blocks_for(self._PEOPLE + [total_row])
        people_block = self._people_block(got)
        idx = people_block["table"]["keys"].index("nm")
        names = [row[idx] for row in people_block["table"]["rows"]]
        self.assertNotIn("계", names, "합계 행이 사람 목록에서 빠지지 않았습니다")
        self.assertIn("오정강", names)
        self.assertIn("오정섭", names)

    def test_aggregate_row_survives_in_its_own_block_not_deleted(self):
        """"합계를 없애라는 게 아니다"(브리프 원칙) — 소계 블록으로
        어딘가에 남아야 한다."""
        total_row = {"nm": "계", "relate": "-", "trmend_posesn_stock_qota_rt": "19.50"}
        got = self._blocks_for(self._PEOPLE + [total_row])
        titles = [b["title"] for b in got]
        self.assertIn("최대주주 · 합계", titles, "합계 블록이 안 보입니다")
        total_block = next(b for b in got if b["title"] == "최대주주 · 합계")
        flat = _flatten_table_cells(total_block["table"])
        self.assertIn("계", flat, "합계 행의 값 자체가 사라졌습니다")

    def test_person_named_starting_with_the_aggregate_word_is_not_misdetected(self):
        """"계상훈"은 진짜 사람이다 — 접두/부분 일치가 아니라 정확히
        "계"/"합계"/"총계"와 같을 때만(splitAggregateRows의 Set.has, trim
        비교) 합계로 분류해야 한다."""
        records = self._PEOPLE + [{"nm": "계상훈", "relate": "특수관계인",
                                     "trmend_posesn_stock_qota_rt": "0.50"}]
        got = self._blocks_for(records)
        people_block = self._people_block(got)
        idx = people_block["table"]["keys"].index("nm")
        names = [row[idx] for row in people_block["table"]["rows"]]
        self.assertIn("계상훈", names, "실제 인물 '계상훈'이 합계로 오탐돼 사람 목록에서 빠졌습니다")
        titles = [b["title"] for b in got]
        self.assertNotIn("최대주주 · 합계", titles,
                          "합계 행이 없는데도(계상훈은 사람이다) 합계 블록이 생겼습니다")

    def test_hap_gye_and_chong_gye_are_also_recognized(self):
        for total_name in ("합계", "총계"):
            records = self._PEOPLE + [{"nm": total_name, "relate": "-",
                                         "trmend_posesn_stock_qota_rt": "19.50"}]
            got = self._blocks_for(records)
            people_block = self._people_block(got)
            idx = people_block["table"]["keys"].index("nm")
            names = [row[idx] for row in people_block["table"]["rows"]]
            self.assertNotIn(total_name, names, f"{total_name} 행이 사람 목록에서 분리되지 않았습니다")

    def test_internal_whitespace_aggregate_name_is_still_recognized(self):
        """DART가 "합 계"처럼 이름 내부에 공백을 넣어 보내는 경우가 있다 —
        trim()은 앞뒤 공백만 없애므로 내부 공백까지 있는 값은 여전히
        AGGREGATE_ROW_NAMES와 정확히 일치하지 않아 사람 목록에 남는다."""
        records = self._PEOPLE + [{"nm": "합 계", "relate": "-",
                                     "trmend_posesn_stock_qota_rt": "19.50"}]
        got = self._blocks_for(records)
        titles = [b["title"] for b in got]
        self.assertIn("최대주주 · 합계", titles,
                      "내부 공백이 있는 '합 계' 행이 합계 블록으로 분리되지 않았습니다")
        people_block = self._people_block(got)
        idx = people_block["table"]["keys"].index("nm")
        names = [row[idx] for row in people_block["table"]["rows"]]
        self.assertNotIn("합 계", names, "'합 계' 행이 여전히 사람 목록에 남아 있습니다")

    def test_person_named_gye_sang_hyeok_is_not_misdetected(self):
        """공백 정규화가 부분/접두 일치로 번지면 "계상혁" 같은 실제 인물이
        오탐될 수 있다 — 정규화는 공백 제거일 뿐이고, 공백이 없는 이름은
        원래 글자 그대로 남아 AGGREGATE_ROW_NAMES의 어떤 항목과도 같아지지
        않아야 한다."""
        records = self._PEOPLE + [{"nm": "계상혁", "relate": "특수관계인",
                                     "trmend_posesn_stock_qota_rt": "0.30"}]
        got = self._blocks_for(records)
        people_block = self._people_block(got)
        idx = people_block["table"]["keys"].index("nm")
        names = [row[idx] for row in people_block["table"]["rows"]]
        self.assertIn("계상혁", names,
                      "실제 인물 '계상혁'이 합계로 오탐돼 사람 목록에서 빠졌습니다")
        titles = [b["title"] for b in got]
        self.assertNotIn("최대주주 · 합계", titles,
                         "합계 행이 없는데도(계상혁은 사람이다) 합계 블록이 생겼습니다")

    def test_no_aggregate_row_present_is_still_safe(self):
        """합계 행이 아예 없는 데이터에서도 사람 목록은 그대로, 합계 블록은
        생기지 않아야 한다."""
        got = self._blocks_for(self._PEOPLE)
        titles = [b["title"] for b in got]
        self.assertIn("최대주주", titles)
        self.assertNotIn("최대주주 · 합계", titles)
        people_block = self._people_block(got)
        idx = people_block["table"]["keys"].index("nm")
        names = [row[idx] for row in people_block["table"]["rows"]]
        self.assertEqual(set(names), {"오정강", "오정섭"})

    def test_empty_major_holders_still_gets_its_own_block(self):
        """빈 리스트는 표를 만들 근거가 없다는 사실 자체를 블록으로
        남긴다 — 기존 원칙(test_empty_nested_list_still_gets_its_own_block)과
        같다."""
        got = self._blocks_for([])
        titles = [b["title"] for b in got]
        self.assertIn("최대주주", titles)

    def test_record_without_nm_field_is_kept_as_a_person_not_dropped(self):
        """판정을 못 하면(예상 밖 응답 — nm 필드 자체가 없음) 지우지 않는
        쪽이 안전하다 — splitAggregateRows 주석의 명시적 규칙."""
        malformed = [{"relate": "본인", "trmend_posesn_stock_qota_rt": "17.40"}]
        got = self._blocks_for(self._PEOPLE + malformed)
        people_block = self._people_block(got)
        self.assertEqual(len(people_block["table"]["rows"]), 3,
                          "nm이 없는 레코드가 사람 목록에서 조용히 사라졌습니다")


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestNormalizeDebtByKind(unittest.TestCase):
    """debt_balance.by_kind({회사채: {total, maturity_under_1y}, ...})는
    dart_client.fetch_debt_balance가 종류를 키로 쓰는 dict다(레코드
    리스트가 아니다, task-6-brief.md) — normalizeDebtByKind가 종류를 열
    (debt_kind)로 뒤집어야 표 하나로 나란히 비교되고 chartData가 그릴
    x축 필드가 생긴다(normalizeRoster와 같은 이유).
    """

    def test_kind_keys_become_a_column_with_korean_labels(self):
        got = run_js(
            'normalizeDebtByKind({corporate_bond:{total:1000,maturity_under_1y:200},'
            ' short_term_bond:{total:500,maturity_under_1y:500}})'
        )
        self.assertEqual([r["debt_kind"] for r in got], ["회사채", "단기사채"])
        self.assertEqual(got[0]["total"], 1000)
        self.assertEqual(got[0]["maturity_under_1y"], 200)

    def test_unlabeled_kind_key_keeps_raw_name(self):
        """label()에 없는 종류가 와도 숨기지 않는다 — 원본 키 그대로 쓴다."""
        got = run_js('normalizeDebtByKind({wholly_unknown_kind:{total:1}})')
        self.assertEqual(got[0]["debt_kind"], "wholly_unknown_kind")

    def test_non_object_input_is_empty_list(self):
        for expr in ("normalizeDebtByKind(null)", "normalizeDebtByKind(undefined)",
                     'normalizeDebtByKind("x")', "normalizeDebtByKind([])"):
            self.assertEqual(run_js(expr), [])

    def test_malformed_kind_value_does_not_crash(self):
        """kind 값이 dict가 아니어도(예상 밖 응답 형태) 죽지 않고
        total/maturity_under_1y가 없는 레코드로 방어적으로 처리한다."""
        got = run_js('normalizeDebtByKind({corporate_bond:"이상한 값"})')
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["debt_kind"], "회사채")


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestDebtBalanceWiredIntoSectionBlocks(unittest.TestCase):
    """normalizeDebtByKind를 정의만 하고 sectionBlocks 경로에 안 꽂으면
    (executive_roster와 같은 부류의 사고, 이 저장소에서 이미 다섯 번 났다)
    by_kind는 여전히 종류마다 조각난 1행 표로 나뉘어 나온다 — 종류를
    나란히 비교할 수도, chartData가 읽을 x축(debt_kind)도 없다.

    sectionBlocks가 실제로 소비하는 것과 같은 3번째 인자(key)를 그대로
    넘겨 실제 진입점을 검증한다.
    """

    def test_debt_balance_key_combines_by_kind_into_one_table(self):
        got = run_js(
            'sectionBlocks({year:"2025", total:1500, by_kind:'
            '{corporate_bond:{total:1000,maturity_under_1y:200},'
            ' short_term_bond:{total:500,maturity_under_1y:500}},'
            ' equity_ratio:null, maturity_1y_share:46.7}, 0, "debt_balance")'
        )
        titled = [b for b in got if b["title"] == "종류별 잔액"]
        self.assertEqual(len(titled), 1, "by_kind가 여러 블록으로 쪼개졌거나 안 보입니다")
        table = titled[0]["table"]
        self.assertEqual(table["orientation"], "horizontal")
        self.assertEqual(len(table["rows"]), 2, "종류가 나란히 비교되는 표가 아닙니다")
        flat = [c for r in table["rows"] for c in r]
        self.assertIn("회사채", flat)
        self.assertIn("단기사채", flat)
        # chartData(x="debt_kind")가 읽을 수 있어야 하므로 records에도
        # 원본 숫자(포맷 전)가 그대로 있어야 한다.
        self.assertEqual(
            sorted(r["debt_kind"] for r in titled[0]["records"]),
            ["단기사채", "회사채"],
        )

    def test_flat_scalar_fields_are_not_lost(self):
        """year·total 등 스칼라 필드는 by_kind 특수 처리와 무관하게 그대로
        남아야 한다 — 값이 사라지는 변경이 아니라 더해지는 변경이어야
        한다(SE-4d Global Constraints)."""
        got = run_js(
            'sectionBlocks({year:"2025", total:1500,'
            ' by_kind:{corporate_bond:{total:1000,maturity_under_1y:200}}},'
            ' 0, "debt_balance")'
        )
        flat_blocks = [b for b in got if b["title"] is None]
        self.assertEqual(len(flat_blocks), 1, "스칼라 필드(year/total) 블록이 사라졌습니다")
        labels = [row[0] for row in flat_blocks[0]["table"]["rows"]]
        self.assertIn("연도", labels)
        self.assertIn("합계", labels)

    def test_other_keys_still_get_fragmented_per_kind_blocks(self):
        """key가 "debt_balance"가 아니면 이 특수 경로를 타면 안 된다 —
        일반 dict-of-dicts 펼치기가 그대로 적용돼야 한다(기존 동작
        무변경, test_mixed_flat_and_nested_keeps_both와 같은 성질)."""
        got = run_js(
            'sectionBlocks({by_kind:{corporate_bond:{total:1000}}}, 0, "other_section")'
        )
        titles = [b["title"] for b in got]
        self.assertTrue(any("회사채" in (t or "") for t in titles),
                         "key 무관 특수 경로를 탔습니다 — 일반 재귀 경로가 아닙니다")

    def test_nested_field_literally_named_by_kind_at_deeper_depth_is_unaffected(self):
        """depth 0이 아닐 때는(재귀 호출) key를 넘기지 않으므로, 하위 키가
        우연히 "by_kind"라는 이름이어도 이 특수 경로를 타면 안 된다."""
        got = run_js(
            'sectionBlocks({wrap:{by_kind:{corporate_bond:{total:1000}}}}, 0, "debt_balance")'
        )
        titles = [b["title"] for b in got]
        self.assertTrue(any("회사채" in (t or "") for t in titles),
                         "깊이 0이 아닌 by_kind 키가 잘못 특수 경로로 빠졌습니다")


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestInsiderTimelineSourceSplit(unittest.TestCase):
    """insider_timeline은 elestock·hyslr·hyslr_chg·exec_treasury 4개
    엔드포인트를 합친 결과다(dart_client.fetch_insider_timeline). 레코드마다
    자기 엔드포인트 필드만 채우고 나머지는 전부 null이라, 한 표로 그리면
    실측(field-inventory)에서 접힌 26개 항목 중 값이 있는 열이 0개인 행이
    나왔다 — 펼쳐도 내용이 없어 보이는 원인. source별로 표를 나누고, 그
    안에서도 전부 빈 열은 뺀다(값이 하나라도 있으면 반드시 남긴다).
    """

    def test_records_with_source_split_into_one_table_per_source(self):
        records = [
            {"source": "elestock", "corp_name": "엔켐", "rcept_no": "1", "nm": "오정강"},
            {"source": "elestock", "corp_name": "엔켐", "rcept_no": "2", "nm": "이승호"},
            {"source": "hyslr", "corp_name": "엔켐", "mxmm_shrholdr_nm": "오정강 외 2인"},
        ]
        got = run_js(f"sectionBlocks({json.dumps(records, ensure_ascii=False)})")
        self.assertEqual(len(got), 2, "source별로 표가 나뉘지 않았습니다")
        titles = [b["title"] for b in got]
        self.assertEqual(len(set(titles)), 2, "표 제목이 source별로 구분되지 않습니다")

    def test_each_table_only_has_its_own_endpoint_fields(self):
        """elestock 표에는 hyslr 전용 필드가, hyslr 표에는 elestock 전용
        필드가 나오면 안 된다 — 서로 다른 엔드포인트 필드가 한 표에 섞이면
        빈 칸 문제가 되돌아온다."""
        records = [
            {"source": "elestock", "nm": "오정강"},
            {"source": "hyslr", "mxmm_shrholdr_nm": "오정강 외 2인"},
        ]
        got = run_js(f"sectionBlocks({json.dumps(records, ensure_ascii=False)})")
        by_title = {b["title"]: b["table"] for b in got}
        elestock_table = by_title["임원·주요주주 소유보고 이력"]
        hyslr_table = by_title["최대주주 현황"]
        self.assertNotIn("mxmm_shrholdr_nm", elestock_table["keys"])
        self.assertNotIn("nm", hyslr_table["keys"])

    def test_column_empty_in_every_row_of_its_group_is_dropped(self):
        """같은 source 그룹 안에서도 값이 전부 비어 있는 열은 빼되, 값이
        하나라도 있는 열은 반드시 남아야 한다."""
        records = [
            {"source": "hyslr_chg", "corp_name": "엔켐", "change_cause": "장내매도", "rm": None},
            {"source": "hyslr_chg", "corp_name": "엔켐", "change_cause": None, "rm": None},
        ]
        got = run_js(f"sectionBlocks({json.dumps(records, ensure_ascii=False)})")
        table = got[0]["table"]
        present = set(table["keys"]) | {c["key"] for c in table["caption"]}
        self.assertNotIn("rm", present, "모든 행이 비어 있는 열이 남아 있습니다")
        self.assertIn("change_cause", present, "값이 하나라도 있는 열이 사라졌습니다")

    def test_no_block_has_a_column_where_every_visible_row_is_blank(self):
        """엔켐 실측과 같은 규모(4개 source 혼합)로도 어떤 표에도 완전히
        빈 열이 남지 않아야 한다(세로·가로 표 모두)."""
        records = [
            {"source": "elestock", "rcept_no": "1", "nm": "오정강", "relate": None},
            {"source": "elestock", "rcept_no": "2", "nm": "이승호", "relate": None},
            {"source": "hyslr", "bsns_year": "2026", "mxmm_shrholdr_nm": "오정강", "rm": None},
            {"source": "hyslr_chg", "bsns_year": "2026", "change_cause": "장내매도", "rm": None},
            {"source": "exec_treasury", "bsns_year": "2026", "repror": "오정강", "bsis_qy": None},
        ]
        got = run_js(f"sectionBlocks({json.dumps(records, ensure_ascii=False)})")
        for block in got:
            t = block["table"]
            if t["orientation"] == "vertical":
                for pair in t["rows"]:
                    self.assertNotEqual(
                        pair[1], "",
                        f"{block['title']} 표의 '{pair[0]}' 값이 비어 있는데 열로 남아 있습니다",
                    )
                continue
            for i, k in enumerate(t["keys"]):
                col_values = [row[i] for row in t["rows"]]
                self.assertTrue(
                    any(v != "" for v in col_values),
                    f"{block['title']} 표의 '{k}' 열이 전부 빈칸입니다",
                )

    def test_records_without_source_field_are_not_split(self):
        """source가 없는 다른 섹션에는 이 분리가 적용되면 안 된다."""
        got = run_js('sectionBlocks([{a:1},{a:2}])')
        self.assertEqual(len(got), 1)

    def test_partial_source_presence_falls_back_to_a_single_table(self):
        """일부 레코드만 source를 가지면(예상 밖 응답) 안전하게 단일
        표로 그린다 — 어중간하게 갈라 데이터를 잃는 쪽보다 낫다."""
        got = run_js('sectionBlocks([{source:"elestock",a:1},{a:2}])')
        self.assertEqual(len(got), 1)

    def test_source_group_title_does_not_collide_with_bulk_holders_label(self):
        """bulk_holders 섹션(fetch_shareholder_status, 최신 현황)과
        elestock(fetch_insider_timeline, 전체 이력)은 서로 다른 데이터다 —
        elestock은 애초에 5% 대량보유가 아니라 임원·주요주주 특정증권
        소유보고다(dart_client.fetch_bulk_holdings docstring 근거, 위
        app.js LABELS 주석 참고). 같은 "5% 대량보유" 라벨을 쓰면 라벨
        충돌 검사에도 걸리고 사용자도 두 표를 구분할 수 없다."""
        got = run_js('sectionBlocks([{source:"elestock",a:1}])')
        self.assertNotEqual(got[0]["title"], "5% 대량보유")

    def test_source_value_is_not_repeated_as_a_mismatched_caption(self):
        """리뷰 지적 ③: 표 제목이 이미 "임원·주요주주 소유보고 이력"
        (label(source))인데 바로 아래 캡션에 "출처: elestock"(원본 값)이
        다시 떴다 — 같은 것을 두 가지로 부르는 표기 불일치. 표 안에서는
        source 필드 자체를 빼서 이 중복을 없앤다(값은 title에 여전히
        남는다 — 숨기는 게 아니다).
        """
        records = [
            {"source": "elestock", "rcept_no": "1", "nm": "오정강"},
            {"source": "elestock", "rcept_no": "2", "nm": "이승호"},
        ]
        got = run_js(f"sectionBlocks({json.dumps(records, ensure_ascii=False)})")
        table = got[0]["table"]
        self.assertEqual(got[0]["title"], "임원·주요주주 소유보고 이력")
        caption_keys = [c["key"] for c in table["caption"]]
        self.assertNotIn("source", table["keys"])
        self.assertNotIn("source", caption_keys,
                         "표 제목이 이미 출처를 말하는데 캡션에도 원본 값이 남아 있습니다")


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestMetaOnlyRecordsGetNoDataNote(unittest.TestCase):
    """task-6: "최대주주 변동현황"·"임원·주요주주 자기주식" 섹션이 빈 표처럼
    보이는 문제의 실측 원인 — DART는 해당 분기에 보고할 변동이 없으면 필드를
    null이나 빈 문자열이 아니라 **문자열 "-"**로 채워 돌려준다(status는
    "000" 정상). 아래 첫 두 픽스처는 2026-07-28 실제 API 호출 결과를 그대로
    옮긴 것이다(엔켐·삼성전자, bsns_year=2025, reprt_code=11011):

      - 엔켐 hyslrChgSttus: 1건, 식별자(rcept_no·corp_cls·corp_code·corp_name·
        stlm_dt) 밖의 필드(change_on·mxmm_shrholdr_nm·posesn_stock_co·
        qota_rt·change_cause·rm) 전부 "-".
      - 삼성전자 tesstkAcqsDspsSttus: 18건 중 다수 행에 실제 수량(bsis_qy
        29,700,000 등)·구분(stock_knd "보통주" 등)이 있다 — "표를 그대로
        보여준다" 쪽을 검증한다.

    세 번째 픽스처(2026 1분기 최대주주 변동현황 필드 모양)는 사용자가 화면에서
    실제로 본 값(17.40%·"기존 최대주주의 시간외 장외매도로 인한 변경")을
    hyslrChgSttus 스키마 그대로 재현한 것이다 — "전부 -"가 아니라 "값이
    있으면"의 대조군이다.
    """

    _ENKEM_HYSLR_CHG_EMPTY = [{
        "source": "hyslr_chg",
        "rcept_no": "20260326001049",
        "corp_cls": "K",
        "corp_code": "01011526",
        "corp_name": "엔켐",
        "change_on": "-",
        "mxmm_shrholdr_nm": "-",
        "posesn_stock_co": "-",
        "qota_rt": "-",
        "change_cause": "-",
        "rm": "-",
        "stlm_dt": "2025-12-31",
        "bsns_year": "2025",
        "reprt_code": "11011",
    }]

    _SAMSUNG_EXEC_TREASURY_FILLED = [
        {
            "source": "exec_treasury",
            "rcept_no": "20260310002820",
            "corp_cls": "Y",
            "corp_code": "00126380",
            "corp_name": "삼성전자",
            "stock_knd": "보통주",
            "acqs_mth1": "배당가능이익범위 이내 취득",
            "acqs_mth2": "직접취득",
            "acqs_mth3": "장내직접취득",
            "bsis_qy": "29,700,000",
            "change_qy_acqs": "118,314,495",
            "change_qy_dsps": "6,040,880",
            "change_qy_incnr": "50,144,628",
            "trmend_qy": "91,828,987",
            "rm": "-",
            "stlm_dt": "2025-12-31",
            "bsns_year": "2025",
            "reprt_code": "11011",
        },
        {
            "source": "exec_treasury",
            "rcept_no": "20260310002820",
            "corp_cls": "Y",
            "corp_code": "00126380",
            "corp_name": "삼성전자",
            "stock_knd": "우선주",
            "acqs_mth1": "배당가능이익범위 이내 취득",
            "acqs_mth2": "신탁계약에 의한취득",
            "acqs_mth3": "수탁자보유물량",
            "bsis_qy": "-",
            "change_qy_acqs": "-",
            "change_qy_dsps": "-",
            "change_qy_incnr": "-",
            "trmend_qy": "-",
            "rm": "-",
            "stlm_dt": "2025-12-31",
            "bsns_year": "2025",
            "reprt_code": "11011",
        },
    ]

    _FILLED_HYSLR_CHG = [{
        "source": "hyslr_chg",
        "rcept_no": "20260415000535",
        "corp_cls": "K",
        "corp_code": "01011526",
        "corp_name": "엔켐",
        "change_on": "2026년 04월 12일",
        "mxmm_shrholdr_nm": "오정강 외 2인",
        "posesn_stock_co": "1,234,567",
        "qota_rt": "17.40",
        "change_cause": "기존 최대주주의 시간외 장외매도로 인한 변경",
        "rm": "-",
        "stlm_dt": "2026-03-31",
        "bsns_year": "2026",
        "reprt_code": "11013",
    }]

    def test_enkem_empty_record_gets_no_data_note(self):
        got = run_js(
            f"sectionBlocks({json.dumps(self._ENKEM_HYSLR_CHG_EMPTY, ensure_ascii=False)})"
        )
        self.assertEqual(len(got), 1)
        self.assertEqual(
            got[0].get("note"), "해당 기간에 보고된 내역이 없습니다.",
            "식별자·메타 필드만 있고 실데이터가 전부 \"-\"인 레코드는 "
            "해당 없음으로 표기해야 합니다",
        )

    def test_enkem_empty_record_keeps_rcept_no_reachable(self):
        """판단이 틀렸을 경우를 대비해 접수번호는 지우지 않는다 —
        사용자가 원문을 직접 열어 확인할 수 있어야 한다."""
        got = run_js(
            f"sectionBlocks({json.dumps(self._ENKEM_HYSLR_CHG_EMPTY, ensure_ascii=False)})"
        )
        table = got[0]["table"]
        present = set(table["keys"]) | {c["key"] for c in table["caption"]}
        self.assertIn("rcept_no", present)

    def test_samsung_filled_record_has_no_note(self):
        """값이 하나라도 있으면(삼성전자 자기주식 실수량) 표를 그대로
        보여준다 — 해당 없음 문구를 붙이면 안 된다."""
        got = run_js(
            f"sectionBlocks({json.dumps(self._SAMSUNG_EXEC_TREASURY_FILLED, ensure_ascii=False)})"
        )
        self.assertEqual(len(got), 1)
        self.assertNotIn("note", got[0])

    def test_filled_hyslr_chg_has_no_note(self):
        """2026 1분기처럼 실제 변동(17.40%)이 있으면 해당 없음으로
        덮으면 안 된다 — 있는 데이터를 없다고 하는 게 더 나쁘다."""
        got = run_js(
            f"sectionBlocks({json.dumps(self._FILLED_HYSLR_CHG, ensure_ascii=False)})"
        )
        self.assertEqual(len(got), 1)
        self.assertNotIn("note", got[0])
        table = got[0]["table"]
        formatted = json.dumps(table, ensure_ascii=False)
        self.assertIn("17.4", formatted)


@unittest.skipUnless(_NODE, "node가 없어 ui.js의 실제 렌더 결과를 검증할 수 없습니다")
class TestMetaOnlyNoteRendersInDom(unittest.TestCase):
    """sectionBlocks가 note를 돌려줘도 ui.js의 blockEl이 실제로 그리지
    않으면 죽은 데이터다(이 저장소에서 반복된 "정의만 있고 배선이 없는"
    사고 유형과 같다) — renderSection을 실제로 실행해 DOM에 문구가
    나오는지 확인한다.
    """

    def test_note_text_appears_in_rendered_dom(self):
        records = TestMetaOnlyRecordsGetNoDataNote._ENKEM_HYSLR_CHG_EMPTY
        got = run_render_section(
            '"insider_timeline"', json.dumps(records, ensure_ascii=False)
        )
        self.assertIn("해당 기간에 보고된 내역이 없습니다.", got["notes"])

    def test_filled_record_does_not_render_the_note(self):
        records = TestMetaOnlyRecordsGetNoDataNote._FILLED_HYSLR_CHG
        got = run_render_section(
            '"insider_timeline"', json.dumps(records, ensure_ascii=False)
        )
        self.assertNotIn("해당 기간에 보고된 내역이 없습니다.", got["notes"])


@unittest.skipUnless(_NODE, "node가 없어 ui.js의 실제 렌더 결과를 검증할 수 없습니다")
class TestInsiderTimelineRenderWiring(unittest.TestCase):
    """sectionBlocks 단독 검증만으로는 renderSection(ui.js) 호출부가 실제로
    이 분기를 타는지 못 잡는다(이 저장소에서 이미 여러 번 난 "정의만 있고
    호출부가 안 바뀐" 사고 유형) — app.js·ui.js를 실제로 함께 실행해
    소제목(h3)이 실제 DOM에 여러 개 나오는지 확인한다.
    """

    def test_multiple_source_tables_render_as_separate_titled_blocks(self):
        records = [
            {"source": "elestock", "rcept_no": "1", "nm": "오정강"},
            {"source": "hyslr", "mxmm_shrholdr_nm": "오정강 외 2인"},
        ]
        got = run_render_section(
            '"insider_timeline"', json.dumps(records, ensure_ascii=False)
        )
        self.assertIn("임원·주요주주 소유보고 이력", got["titles"])
        self.assertIn("최대주주 현황", got["titles"])


@unittest.skipUnless(_NODE, "node가 없어 ui.js의 실제 렌더 결과를 검증할 수 없습니다")
class TestFundUsagePayDeLabelAndNote(unittest.TestCase):
    """pay_de 라벨이 "자금 납입일"로 바뀌었는지, fund_usage를 렌더링할 때
    ui.js의 안내 문구가 실제로 DOM에 그려지는지 검증한다.

    "정의만 있고 부르는 곳이 없다" 사고가 이 저장소에서 다섯 번(브리프
    지적) 났으므로, ui.js 소스 문자열에 안내 문구가 있는지가 아니라
    renderSection을 실제로 실행해(app.js·ui.js를 같은 vm에서 순서대로
    실행하는 run_render_section) DOM에 그 문단이 붙는지로 확인한다.
    """

    def test_pay_de_label_is_fund_payment_date(self):
        got = run_js(
            'tableLayout([{tm:"제14회",pay_de:"20211026",pay_amount:1000},'
            ' {tm:"제15회",pay_de:"20220101",pay_amount:2000}])'
        )
        self.assertIn("자금 납입일", got["columns"], "pay_de 라벨이 '자금 납입일'이 아닙니다")
        # 라벨만 바뀐 것이지 날짜 표시 형식(DATE_FIELDS)이 깨지면 안 된다.
        key_idx = got["keys"].index("pay_de")
        self.assertEqual(got["rows"][0][key_idx], "2021.10.26")

    def test_fund_usage_note_is_actually_rendered_in_the_dom(self):
        records = [
            {"tm": "제14회", "kind": "public", "year": 2021, "pay_de": "20211026",
             "pay_amount": 1000, "plan_amount": 1000, "plan_useprps": "원재료 매입",
             "real_dtls_cn": "원재료 매입", "real_dtls_amount": 1000,
             "dffrnc_resn": "-", "flags": []},
        ]
        got = run_render_section('"fund_usage"', json.dumps(records, ensure_ascii=False))
        notes = " ".join(got.get("notes", []))
        self.assertIn("같은 회차가 여러 행으로 나오는 것은 오류가 아닙니다", notes,
                       "fund_usage 안내 문구가 실제 DOM에 그려지지 않았습니다 — "
                       "정의만 있고 renderSection이 부르지 않을 수 있습니다")
        self.assertIn("자금 납입일", notes, "안내 문구가 '자금 납입일' 표현을 쓰지 않습니다")

    def test_note_is_not_rendered_for_other_sections(self):
        """안내문이 fund_usage 전용이어야 한다 — 조건 없이 항상 붙는
        회귀(다른 섹션에도 새는 것)를 잡는다."""
        got = run_render_section(
            '"affiliates"', json.dumps([{"inv_prm": "Enchem Poland"}], ensure_ascii=False)
        )
        notes = " ".join(got.get("notes", []))
        self.assertNotIn("같은 회차가 여러 행으로", notes,
                          "fund_usage 안내문이 다른 섹션(affiliates)에도 그려졌습니다")


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestGroupRouting(unittest.TestCase):
    """SECTION_GROUPS를 실제로 소비하는 groupTitleFor/groupOrderIndex 검증.

    브리프에 Consumes: SECTION_GROUPS라고 적혀 있었는데 실제 구현이
    아무도 이 상수를 읽지 않아 그룹 제목·순서가 화면에 전혀 안 나오던
    문제의 수정 대상.
    """

    def test_known_key_maps_to_its_group_title(self):
        self.assertEqual(run_js('groupTitleFor("shareholders")'), "지배구조")
        self.assertEqual(run_js('groupTitleFor("audit_history")'), "감사·부실")

    def test_unknown_key_falls_back_to_catchall_group(self):
        """2단 `doc:<rcept_no>` 키(개별 원문 섹션, addDocListEntry가 목록
        하나로 모으기 전의 원본 키)처럼 SECTION_GROUPS에 없는 키도 어딘가에는
        나와야 한다 — 그룹이 없다고 사라지면 안 된다. 이 개별 키 자체는
        renderSection에 직접 넘어가지 않으므로(DOC_LIST_KEY로 모아서만
        그린다) "기타"로 떨어지는 것이 실제로는 문제가 안 된다 — 아래
        doc_list(목록 키) 테스트와는 별개다.
        """
        got = run_js('groupTitleFor("doc:20240301000001")')
        self.assertEqual(got, "기타")

    def test_doc_list_gets_its_own_section_not_the_catchall(self):
        """doc_list(공시 원문 목록, DOC_LIST_KEY)는 STAGE1_SPECS에 없는
        합성 키지만 실제로 renderSection(ui.js)에 그대로 넘어가 화면에
        그려진다 — "기타"로 떨어지면 design 문서(§7.1)가 정의한 "⑦ 공시
        원문 열람" 자리 대신 페이지 맨 끝(다른 어떤 그룹보다도 뒤)으로
        밀려난다. 리뷰 지적 ②의 재발 방지.
        """
        got = run_js('groupTitleFor("doc_list")')
        self.assertNotEqual(got, "기타")
        self.assertEqual(got, "공시 원문 열람")

    def test_group_order_follows_definition_order(self):
        got = [run_js(f'groupOrderIndex("{t}")') for t in
               ("자금", "재무", "지배구조", "감사·부실", "공시 원문 열람")]
        self.assertEqual(got, sorted(got), "그룹 순서가 정의 순서를 따르지 않습니다")

    def test_doc_list_group_sorts_after_the_last_stage1_group(self):
        """design 문서 §7.1은 "⑦ 공시 원문 열람"을 감사·부실 뒤 마지막
        정식 섹션으로 정의한다 — "기타"보다는 앞이어야 한다."""
        audit = run_js('groupOrderIndex("감사·부실")')
        doc_list_group = run_js('groupOrderIndex("공시 원문 열람")')
        catchall = run_js('groupOrderIndex("기타")')
        self.assertLess(audit, doc_list_group)
        self.assertLess(doc_list_group, catchall)

    def test_unknown_group_sorts_after_all_known_groups(self):
        known_max = max(
            run_js(f'groupOrderIndex("{t}")')
            for t in ("자금", "재무", "지배구조", "감사·부실", "공시 원문 열람")
        )
        self.assertGreater(run_js('groupOrderIndex("기타")'), known_max)


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestActorLine(unittest.TestCase):
    def test_verified_has_label(self):
        got = run_js('actorLine({name:"홍길동", status:"verified", companies:["A"]})')
        self.assertEqual(got["name"], "홍길동")
        self.assertTrue(got["statusLabel"])

    def test_auto_matched_carries_namesake_warning(self):
        """자동 매칭은 동명이인이 확인되지 않았다. 경고 없이 실명을
        보여주면 안 된다."""
        got = run_js('actorLine({name:"홍길동", status:"auto_matched", companies:[]})')
        self.assertIn("동명이인", got["warn"])

    # test_unknown_status_is_treated_as_weakest는 삭제했다 — "모르는 값이
    # 강한 쪽으로 승격되지 않는다"를 검증하려 했지만, 세 status가 전부
    # 동명이인 경고를 갖는다(위 test_every_known_status_also_carries_the_
    # namesake_warning)는 사실 때문에 warn에 "동명이인"이 있는지만 봐서는
    # 실제로 auto_matched로 떨어졌는지 verified로 잘못 승격됐는지 구분하지
    # 못했다(공허 통과 — 뮤테이션으로 확인됨). 바로 아래
    # test_unknown_status_label_matches_auto_matched_exactly가 같은 입력
    # 목록으로 statusLabel을 직접 대조해 승격 여부를 정확히 잡으므로
    # (그리고 auto_matched로 떨어지면 warn도 자동으로 동명이인을 포함한다는
    # 것은 다른 테스트가 보장한다), 완전히 상위호환으로 대체된다.

    def test_unknown_status_label_matches_auto_matched_exactly(self):
        """세 단계 모두 '동명이인' 문구를 포함하므로(위 테스트) warn 문구
        하나만으로는 unknown이 실제로 auto_matched로 떨어졌는지, 아니면
        더 강한 verified로 잘못 승격됐는지 구분할 수 없다 — 둘 다 warn에
        '동명이인'이 들어 있기 때문이다(뮤테이션으로 실제 확인됨: 폴백을
        ACTOR_STATUS.verified로 바꿔도 위 테스트는 통과했다). label을
        직접 대조해 승격 여부를 명확히 잡는다.
        """
        known = run_js('actorLine({name:"홍길동", status:"auto_matched", companies:[]})')
        for bad in ('""', '"확인됨"', "null", "123", '["verified"]'):
            got = run_js(f'actorLine({{name:"홍길동", status:{bad}, companies:[]}})')
            self.assertEqual(got["statusLabel"], known["statusLabel"],
                             f"status={bad}가 auto_matched 라벨로 떨어지지 않았습니다")

    def test_every_known_status_also_carries_the_namesake_warning(self):
        """레지스트리 대조는 표기 일치이지 신원 확인이 아니므로, verified·
        maintainer_seed도 auto_matched와 마찬가지로 동명이인 경고를 가져야
        한다(브리프: "세 단계 모두 동명이인 경고를 갖는다"). 근거 강도
        차이는 label이 나타내지 warn의 유무가 나타내지 않는다.
        """
        for st in ('"verified"', '"maintainer_seed"', '"auto_matched"'):
            got = run_js(f'actorLine({{name:"홍길동", status:{st}, companies:[]}})')
            self.assertIn("동명이인", got["warn"], f"status={st}에 경고가 없습니다")

    def test_every_status_produces_a_label(self):
        """라벨이 빈 채로 실명만 나가는 경로가 있으면 안 된다."""
        for st in ('"verified"', '"maintainer_seed"', '"auto_matched"', '""'):
            got = run_js(f'actorLine({{name:"홍길동", status:{st}, companies:[]}})')
            self.assertTrue(got["statusLabel"], f"status={st}에 라벨이 없습니다")

    def test_missing_name_does_not_crash(self):
        got = run_js("actorLine({})")
        self.assertEqual(got["name"], "")


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestResumeTarget(unittest.TestCase):
    _HOUR = 3600 * 1000

    def test_recent_job_is_resumed(self):
        got = run_js(f'resumeTarget({{job_id:"j1", saved_at: {10 * self._HOUR}}},'
                     f' {10 * self._HOUR + 60000})')
        self.assertEqual(got, "j1")

    def test_stale_job_is_not_resumed(self):
        """며칠 전 작업을 조용히 이어받으면 새 분석으로 오해한다."""
        got = run_js(f'resumeTarget({{job_id:"j1", saved_at: 0}}, {72 * self._HOUR})')
        self.assertIsNone(got)

    def test_missing_or_malformed_is_null(self):
        for expr in ("resumeTarget(null, 1)", "resumeTarget({}, 1)",
                     'resumeTarget({job_id:"j"}, 1)'):
            self.assertIsNone(run_js(expr), f"{expr}가 이어받으려 합니다")

    def test_boundary_at_exactly_the_resume_window_is_still_resumed(self):
        """정확히 경계(12시간)는 포함이다 — <=이지 <가 아니다."""
        got = run_js('resumeTarget({job_id:"j1", saved_at: 0}, 12 * 3600 * 1000)')
        self.assertEqual(got, "j1")

    def test_one_ms_past_the_boundary_is_not_resumed(self):
        got = run_js('resumeTarget({job_id:"j1", saved_at: 0}, 12 * 3600 * 1000 + 1)')
        self.assertIsNone(got)


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestSectionBlocksDepthGuard(unittest.TestCase):
    """sectionBlocks의 재귀 깊이 상한 — (c) 앞 리뷰 지적: 값이 서버 응답의
    JSON.parse 산물이라 현재는 도달 불가하지만, 터지면 analyze()의 폴링
    루프가 예외를 삼키며 조용히 멈춘다. 상한에 걸린 값은 숨기지 않고
    표현해야 한다(이 화면의 원칙).
    """

    def _deeply_nested(self, depth: int) -> str:
        # {"k": {"k": {"k": ... "leaf": 1}}}
        js = "1"
        for _ in range(depth):
            js = '{"k":' + js + "}"
        return js

    def test_pathologically_deep_value_does_not_crash_and_is_not_silently_dropped(self):
        """깊이 상한이 없으면 200단 중첩도 끝까지 재귀해 캡 문구 없이
        완주한다(스택이 아직 안 터지는 얕은 깊이라 크래시로는 못 잡는다) —
        그래서 "터지지 않는다"가 아니라 "상한 문구가 실제로 나온다"를
        검사해야 상한 도입 자체를 검증한다.
        """
        deep = self._deeply_nested(200)
        got = run_js(f"sectionBlocks({deep})")
        self.assertNotEqual(got, [], "깊이 상한에 걸린 값이 흔적 없이 사라졌습니다")
        texts = [b.get("text") for b in got if b.get("text")]
        self.assertTrue(
            any("깊이" in t for t in texts),
            "상한에 걸렸다는 사실이 어떤 블록에도 나타나지 않습니다 — "
            "데이터가 조용히 잘렸을 수 있습니다",
        )

    # test_normal_shallow_nesting_is_unaffected는 삭제했다 — 같은 입력
    # (major_holders/bulk_holders 2단 중첩)과 같은 세 검사(블록 2개,
    # "최대주주"·"5% 대량보유" 타이틀 존재)를 TestSectionBlocks의
    # test_dict_of_lists_splits_into_titled_blocks가 이미 그대로 수행한다
    # (그쪽이 표 not-None 검사까지 하나 더 있어 오히려 상위호환) — 상한
    # 도입이 정상 케이스를 깨지 않는다는 확인은 그 테스트로 이미 충분하다.


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestExecutiveRoster(unittest.TestCase):
    """fetch_executive_roster(dart_client.py)는 {임원명: {연도}}(set)를 돌려주고,
    se_server/jobs/runner.py의 _jsonable이 set을 정렬된 list로 낮춰 JSON화한다
    (실측 docs/superpowers/plans/2026-07-27-se-4c-field-inventory.json:
    executive_roster는 1건×7열, 열 이름이 전부 사람 이름이다).

    이름을 열 제목으로 쓰면 임원 7명일 때 7열짜리 1행 표가 되어 못 읽는다
    — normalizeRoster가 사람을 행으로 뒤집는다.
    """

    _SAMPLE = '{"김기범":["2025","2026"],"박시묵":["2026"]}'

    def test_names_become_rows_not_columns(self):
        got = run_js(f'normalizeRoster({self._SAMPLE})')
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0]["성명"], "김기범")

    def test_years_are_joined_readably(self):
        got = run_js(f'normalizeRoster({self._SAMPLE})')
        self.assertIn("2025", got[0]["재직 연도"])
        self.assertIn("2026", got[0]["재직 연도"])

    def test_year_set_object_form_is_handled(self):
        """연도가 배열이 아니라 객체로 올 수도 있다."""
        got = run_js('normalizeRoster({"김기범":{"2026":true}})')
        self.assertEqual(got[0]["성명"], "김기범")

    def test_non_object_input_is_empty_list(self):
        for expr in ("normalizeRoster(null)", 'normalizeRoster("x")', "normalizeRoster([])"):
            self.assertEqual(run_js(expr), [])

    def test_no_name_is_dropped(self):
        got = run_js('normalizeRoster({"가":[],"나":[],"다":[]})')
        self.assertEqual([r["성명"] for r in got], ["가", "나", "다"])


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestExecutiveRosterWiredIntoSectionBlocks(unittest.TestCase):
    """normalizeRoster를 정의만 하고 sectionBlocks 경로에 안 꽂으면(이 저장소에서
    이미 세 번 난 사고 유형) 화면은 여전히 이름을 열 제목으로 그린다 —
    normalizeRoster 단독 테스트만으로는 이 배선 누락을 못 잡는다.

    sectionBlocks가 실제로 소비하는 것과 같은 3번째 인자(key)를 그대로
    넘겨 실제 진입점을 검증한다.
    """

    def test_executive_roster_key_routes_through_normalize_roster(self):
        got = run_js(
            'sectionBlocks({"김기범":["2025","2026"],"박시묵":["2026"]}, 0, "executive_roster")'
        )
        self.assertEqual(len(got), 1, "임원현황이 여러 블록으로 쪼개졌습니다")
        table = got[0]["table"]
        self.assertIsNotNone(table, "임원현황 표가 없습니다")
        self.assertIn("성명", table["keys"])
        self.assertIn("재직 연도", table["keys"])
        flat = [c for r in table["rows"] for c in r]
        self.assertIn("김기범", flat)
        self.assertIn("박시묵", flat)

    def test_other_keys_are_not_affected(self):
        """key가 "executive_roster"가 아니면 이 특수 경로를 타면 안 된다
        (예: shareholders는 기존 dict-of-lists 펼치기를 그대로 써야 한다)."""
        got = run_js(
            'sectionBlocks({major_holders:[{nm:"a"}]}, 0, "shareholders")'
        )
        titles = [b["title"] for b in got]
        self.assertIn("최대주주", titles)

    def test_nested_field_literally_named_executive_roster_is_unaffected(self):
        """depth 0이 아닐 때는(재귀 호출) key를 넘기지 않으므로, 하위 키가
        우연히 "executive_roster"라는 이름이어도 이 특수 경로를 타면 안
        된다 — 사람 이름이 아닌 일반 dict-of-lists로 그대로 펼쳐져야
        한다."""
        got = run_js(
            'sectionBlocks({executive_roster:{major_holders:[{nm:"a"}]}})'
        )
        titles = [b["title"] for b in got]
        self.assertTrue(any("최대주주" in (t or "") for t in titles),
                         "중첩된 executive_roster 키가 사람 명단 경로로 잘못 빠졌습니다")


@unittest.skipUnless(_NODE, "node가 없어 ui.js의 실제 렌더 경로를 검증할 수 없습니다")
class TestExecutiveRosterRenderWiring(unittest.TestCase):
    """renderSection(key, value) → sectionBlocks(value, 0, key) 로 실제 key가
    전달되는지를, app.js·ui.js를 node vm에 함께 실행해 DOM 결과로 확인한다.

    normalizeRoster와 sectionBlocks 안의 분기는 만들어놓고 ui.js의 호출부
    (renderSection)가 key를 안 넘기면, 화면에서는 여전히 임원 이름이 소제목
    (h3)으로 하나씩 떨어져 나온다 — 사람이 여전히 열/블록 제목이 되는
    회귀다. 표 셀 값으로 이름이 나오는지, 그리고 이름이 h3 제목으로
    떨어지지 않는지를 함께 확인해야 이 경로 전체(진짜 렌더 경로)가
    배선됐다고 말할 수 있다.
    """

    def test_names_render_as_table_cells_not_section_titles(self):
        got = run_render_section(
            '"executive_roster"',
            '{"김기범":["2025","2026"],"박시묵":["2026"]}',
        )
        self.assertIn("김기범", got["cells"], "임원 이름이 표 셀에 없습니다")
        self.assertIn("박시묵", got["cells"], "임원 이름이 표 셀에 없습니다")
        self.assertNotIn("김기범", got["titles"],
                          "이름이 여전히 소제목(h3)으로 떨어져 나옵니다 — "
                          "renderSection이 key를 sectionBlocks에 넘기지 않는 회귀입니다")
        self.assertNotIn("박시묵", got["titles"])


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestLabels(unittest.TestCase):
    def test_known_dart_fields_get_korean_labels(self):
        cases = {
            "rm": "비고", "flr_nm": "공시제출인", "report_nm": "공시명",
            "tm": "회차", "inv_prm": "피출자 법인명", "lwfr": "전전기",
            "plan_amount": "계획 금액", "real_dtls_amount": "실제 집행 금액",
            "maturity_under_1y": "1년 이내 만기 금액", "company_info": "기업 개요",
        }
        for key, want in cases.items():
            self.assertEqual(run_js(f'label({json.dumps(key)})'), want)

    def test_reprt_code_label_names_a_category_not_a_code(self):
        """reprt_code의 값 자체는 REPRT_CODE_LABELS(formatValue)가 이미
        "1분기보고서" 같은 한국어로 바꾼다 — 그런데 열 라벨(키)이 여전히
        "보고서코드"면 "보고서코드: 1분기보고서"처럼 코드가 아닌 값에
        '코드'라는 이름이 붙어 읽힌다. 라벨도 값처럼 구분을 말해야 한다."""
        self.assertEqual(run_js('label("reprt_code")'), "보고서 구분")
        self.assertNotEqual(run_js('label("reprt_code")'), "보고서코드")

    def test_unknown_field_keeps_raw_key(self):
        """라벨이 없다고 숨기거나 바꾸면 안 된다."""
        self.assertEqual(run_js('label("totally_unknown_xyz")'), "totally_unknown_xyz")

    def test_label_is_not_fooled_by_prototype_keys(self):
        for key in ("toString", "constructor", "__proto__", "hasOwnProperty"):
            self.assertEqual(run_js(f'label({json.dumps(key)})'), key)

    def test_every_label_is_a_nonempty_string(self):
        """빈 라벨이 들어가면 열 제목이 사라진다."""
        labels = run_js("LABELS")
        bad = [k for k, v in labels.items() if not isinstance(v, str) or not v.strip()]
        self.assertEqual(bad, [], f"빈 라벨: {bad}")

    def test_no_label_collides_with_a_different_raw_key(self):
        """서로 다른 필드가 같은 한국어 라벨을 가지면 열을 구분할 수 없다."""
        labels = run_js("LABELS")
        seen = {}
        dup = []
        for k, v in labels.items():
            if v in seen:
                dup.append(f"{seen[v]}·{k} → {v}")
            seen[v] = k
        self.assertEqual(dup, [], "라벨이 겹칩니다:\n  " + "\n  ".join(dup))


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestFormatValue(unittest.TestCase):
    def test_large_amount_becomes_readable_korean_unit(self):
        self.assertEqual(run_js('formatValue("plan_amount", 13082000000)'), "130.8억")

    def test_trillion_scale(self):
        self.assertEqual(run_js('formatValue("plan_amount", 1300000000000)'), "1.3조")

    def test_small_amount_keeps_thousands_separator(self):
        self.assertEqual(run_js('formatValue("plan_amount", 4500)'), "4,500")

    def test_zero_is_zero_not_blank(self):
        """0을 빈칸으로 만들면 잘못된 정보다."""
        self.assertEqual(run_js('formatValue("plan_amount", 0)'), "0")

    def test_yyyymmdd_becomes_dotted_date(self):
        self.assertEqual(run_js('formatValue("rcept_dt", "20260724")'), "2026.07.24")

    def test_hyphenated_iso_date_becomes_dotted_too(self):
        """리뷰 지적 ③: insider_timeline의 rcept_dt 실측(field-inventory)은
        "2026-04-15"처럼 하이픈이 있는 형태다. 차트 축(axisLabel)은 이미
        이 형태를 "."으로 바꾸는데 표(formatValue)가 8자리 숫자만 처리하면
        표는 하이픈 그대로, 차트는 점 표기로 같은 값을 두 가지로 보여준다."""
        self.assertEqual(run_js('formatValue("rcept_dt", "2026-04-15")'), "2026.04.15")

    def test_rcept_no_is_never_reformatted_as_a_date(self):
        """접수번호는 14자리 숫자다. 날짜로 오인하면 안 된다."""
        self.assertEqual(run_js('formatValue("rcept_no", "20260724000552")'),
                         "20260724000552")

    def test_non_amount_field_with_big_number_is_untouched(self):
        """금액 필드가 아닌데 큰 수라고 억으로 바꾸면 거짓말이 된다."""
        self.assertEqual(run_js('formatValue("corp_code", "01011526")'), "01011526")

    def test_null_becomes_empty_string(self):
        self.assertEqual(run_js('formatValue("plan_amount", null)'), "")

    def test_negative_amount_keeps_sign(self):
        self.assertEqual(run_js('formatValue("plan_amount", -13082000000)'), "-130.8억")

    def test_maturity_under_1y_is_treated_as_amount(self):
        """by_kind[종류].maturity_under_1y는 원 단위 금액이다
        (dart_client.fetch_debt_balance). AMOUNT_FIELDS에 없으면 천단위
        구분조차 없는 생숫자로 나간다 — 엔켐 실측에서 잡힌 사각지대."""
        self.assertEqual(run_js('formatValue("maturity_under_1y", 13082000000)'), "130.8억")

    def test_trillion_boundary_rounds_up_past_10000_eok(self):
        """999999999999(1e12 바로 아래)는 억 단위로 반올림하면 "10000억"이
        되는데, 거짓은 아니지만 "1조"가 자연스럽다."""
        self.assertEqual(run_js('formatValue("plan_amount", 999999999999)'), "1조")

    def test_trillion_boundary_exact_switchover_point(self):
        """9999.95억(반올림 전 마지막 값)부터 "1조"로 넘어가고, 그 바로
        아래는 여전히 "9999.9억"이어야 한다 — 어디서 단위가 바뀌는지
        명확해야 한다."""
        self.assertEqual(run_js('formatValue("plan_amount", 999995000000)'), "1조")
        self.assertEqual(run_js('formatValue("plan_amount", 999994999999)'), "9999.9억")

    def test_empty_array_reads_as_none_not_bracket_literal(self):
        """fund_usage의 flags: []가 캡션에 "이상 표시: []"로 뜨던 문제
        (리뷰 지적 ⑥) — 빈 배열은 "없음"으로 명확히 말해야 한다."""
        self.assertEqual(run_js('formatValue("flags", [])'), "없음")

    def test_non_empty_array_of_strings_reads_as_comma_joined(self):
        """JSON.stringify(["a","b"]) === '["a","b"]'는 대괄호·따옴표가
        섞여 사람이 읽기 불편하다 — 쉼표로 이어 붙인다."""
        self.assertEqual(
            run_js('formatValue("flags", ["FUND_DIVERSION","FUND_UNREPORTED"])'),
            "FUND_DIVERSION, FUND_UNREPORTED",
        )

    def test_array_of_objects_keeps_each_item_as_json(self):
        """배열 원소가 객체면 그 원소만 JSON으로 남긴다 — 배열 자체를
        문자열 하나로 뭉개 원소 경계를 잃지 않는다."""
        got = run_js('formatValue("x", [{"a":1},{"b":2}])')
        self.assertIn('"a":1', got.replace(" ", ""))
        self.assertIn('"b":2', got.replace(" ", ""))


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestDocKeyRceptNo(unittest.TestCase):
    """registry.py의 expand_stage2가 만드는 `f"doc:{rcept_no}"` 키에서
    접수번호를 뽑는다 — ui.js가 이 값으로 본문 목록 통합(addDocListEntry)
    분기를 태운다."""

    def test_extracts_rcept_no_from_doc_prefixed_key(self):
        self.assertEqual(
            run_js('docKeyRceptNo("doc:20260715900769")'), "20260715900769"
        )

    def test_non_doc_key_is_null(self):
        for expr in (
            'docKeyRceptNo("insider_timeline")',
            'docKeyRceptNo("doc")',
            "docKeyRceptNo(null)",
            "docKeyRceptNo(123)",
        ):
            self.assertIsNone(run_js(expr), f"{expr}가 doc: 키로 잘못 인식됐습니다")


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestDocListRow(unittest.TestCase):
    """doc:<접수번호> 섹션 값(원문 최대 20,000자 포함)을 본문 목록 한 줄로
    줄인다 — 원문 자체는 목록에 넣지 않는다(사용자 승인 방향: 원문은
    우측 패널에서 본다), 몇 자짜리 문서인지·잘렸는지는 남긴다.
    """

    def test_row_carries_rcept_no_char_count_and_truncated(self):
        got = run_js(
            'docListRow("20260715900769",'
            ' {text:"본문 내용", char_count:3988, truncated:false,'
            '  main_file:"20260715900769.xml", files:["20260715900769.xml"]})'
        )
        self.assertEqual(got["rcept_no"], "20260715900769")
        self.assertEqual(got["char_count"], 3988)
        self.assertEqual(got["truncated"], False)

    def test_full_text_is_not_carried_into_the_row(self):
        """행에 원문 전체가 실리면 목록으로 나눈 의미가 없다."""
        got = run_js(
            'docListRow("1", {text:"가".repeat(4000), char_count:4000, truncated:false})'
        )
        self.assertNotIn("text", got, "원문 전체가 목록 행에 그대로 남아 있습니다")

    def test_missing_value_does_not_crash(self):
        got = run_js('docListRow("1", null)')
        self.assertEqual(got["rcept_no"], "1")
        self.assertEqual(got["files"], [], "value가 없어도 files는 빈 배열이어야 합니다")

    def test_row_carries_main_file_and_files(self):
        """리뷰 지적 ①: main_file·files가 본문 어디에서도 도달 불가였다 —
        se_server/api/handlers.py의 우측 패널 응답(`_disclosure`)은
        rcept_no·text·char_count·truncated만 주므로, 목록에서마저 빠지면
        이 두 필드는 화면 전체에서 사라진다. 실측(field-inventory) 기준
        34건 중 33건이 main_file에 실제 파일명을 갖고 있다.
        """
        got = run_js(
            'docListRow("20260715900769",'
            ' {text:"x", char_count:1, truncated:false,'
            '  main_file:"20260715900769.xml", files:["20260715900769.xml"]})'
        )
        self.assertEqual(got["main_file"], "20260715900769.xml")
        self.assertEqual(got["files"], ["20260715900769.xml"])

    def test_row_normalizes_non_array_files_to_empty_list(self):
        """files가 배열이 아닌 예상 밖 값이면(예상 밖 응답) 조용히 무너지지
        않고 빈 배열로 안전하게 떨어진다."""
        got = run_js(
            'docListRow("1", {char_count:0, truncated:false, files:null})'
        )
        self.assertEqual(got["files"], [])

    def test_doc_prefixed_key_is_stripped_from_rcept_no(self):
        """실측 결함 재현: 호출부가 docKeyRceptNo로 미리 벗기지 않고
        섹션 키(`doc:<접수번호>`)를 그대로 넘겨도 rcept_no 열에 접두어가
        남으면 안 된다. 접두어가 남으면 openDocPanel(ui.js)이
        `/api/se/disclosure/doc%3A...`를 요청하는데, se_server/api/router.py의
        rcept_no 패턴(`[0-9]{8,20}`, 숫자만)과 매칭되지 않아 404가 난다 —
        프로덕션 실측: `/api/se/disclosure/doc%3A20260715900769` → 404.
        지금 유일한 호출부(ui.js addDocListEntry)는 이미 docKeyRceptNo로
        벗겨 넘기지만, docListRow 자신도 이 계약을 지켜야 다른 호출부가
        실수해도 같은 사고가 재발하지 않는다.
        """
        got = run_js(
            'docListRow("doc:20260715900769",'
            ' {char_count:1, truncated:false})'
        )
        self.assertEqual(got["rcept_no"], "20260715900769")
        self.assertNotIn("doc:", got["rcept_no"])

    def test_already_stripped_rcept_no_passes_through_unchanged(self):
        """정상 호출부(ui.js)가 이미 벗긴 값을 넘기는 경우 — 이중 처리로
        값이 훼손되면 안 된다."""
        got = run_js(
            'docListRow("20260715900769",'
            ' {char_count:1, truncated:false})'
        )
        self.assertEqual(got["rcept_no"], "20260715900769")

    def test_empty_files_is_shown_as_a_fact_not_a_verdict(self):
        """리뷰 지적 ④: ZIP을 아예 못 받은 공시는 files가 빈 배열로 온다
        (se_server/api/handlers.py `_disclosure`의 files=[] 판별 기준과
        동일). 목록에서 클릭하기 전에 미리 알 수 있어야 하지만, "실패"·
        "오류" 같은 판정 어휘 없이 사실만 표기해야 한다(v0.8.5 원칙) —
        formatValue(app.js)의 빈 배열 규칙("없음")이 그 역할을 한다.
        """
        row = run_js(
            'docListRow("20260123000072",'
            ' {text:"", char_count:0, truncated:false, main_file:"", files:[]})'
        )
        self.assertEqual(row["files"], [])
        rendered = run_js(f'formatValue("files", {json.dumps(row["files"])})')
        self.assertEqual(rendered, "없음")
        for verdict_word in ("실패", "오류", "에러"):
            self.assertNotIn(verdict_word, rendered)


@unittest.skipUnless(_NODE, "node가 없어 ui.js의 실제 클릭 배선을 검증할 수 없습니다")
class TestDocPanelClickWiring(unittest.TestCase):
    """공시 원문 패널은 rcept_no 셀 클릭에서만 열려야 한다(브리프 ①·②).

    이전 정적 검사(test_se_page_assets.py의
    test_open_doc_panel_is_wired_from_the_rcept_no_cell)는 tableEl 본문에
    "rcept_no"·"openDocPanel(" 문자열이 있는지만 봤다 — 그래서 캡션 승격이
    실제로 배선을 끊었는데도(affiliates·financials는 rcept_no가 상수열이라
    캡션으로 승격되고, 캡션 div는 예전엔 textContent만이라 클릭이 안 됐다)
    계속 초록이었다. 여기서는 app.js·ui.js를 node vm 가짜 DOM에 실제로
    실행해 tableLayout → tableEl → 클릭 이벤트까지 전체 경로를 재현한다.
    """

    def test_horizontal_table_rcept_no_column_is_clickable(self):
        """rcept_no가 행마다 달라 표 본문 열로 남는 일반적인 경우다."""
        got = run_doc_click(
            '[{rcept_no:"20260101000001",n:1},{rcept_no:"20260102000002",n:2}]'
        )
        self.assertEqual(got["orientation"], "horizontal")
        self.assertEqual(sorted(got["captured"]),
                         ["20260101000001", "20260102000002"])

    def test_vertical_table_rcept_no_row_is_clickable(self):
        """레코드 1건(예: indicators)이면 세로 — rows[i]가 [라벨, 값]이라
        가로와 셀 위치가 달라 배선을 따로 확인해야 한다(브리프 ②: "세로
        표의 rcept_no 배선에는 커밋된 테스트가 0건이었다")."""
        got = run_doc_click('[{rcept_no:"20260724000552",n:1}]')
        self.assertEqual(got["orientation"], "vertical")
        self.assertEqual(got["captured"], ["20260724000552"])

    def test_constant_rcept_no_promoted_to_caption_is_still_clickable(self):
        """affiliates(27줄)·financials(30줄) 실측 — rcept_no가 모든 행에서
        같아 tableLayout이 이 열을 표 본문(keys)에서 빼 캡션으로 올린다.
        이 경우에도 공시 원문 패널을 열 수 있어야 한다(브리프 ①, Critical)
        — 안 그러면 이 두 섹션에서는 패널에 도달할 방법 자체가 없어진다.
        """
        got = run_doc_click(
            '[{rcept_no:"20260715900769",corp_name:"엔켐",inv_prm:"A"},'
            ' {rcept_no:"20260715900769",corp_name:"엔켐",inv_prm:"B"}]'
        )
        self.assertEqual(got["orientation"], "horizontal")
        caption_keys = [c["key"] for c in got["caption"]]
        self.assertIn("rcept_no", caption_keys,
                     "이 테스트 자체가 재현하려는 전제(rcept_no가 상수라 "
                     "캡션으로 승격됨)가 깨졌습니다")
        self.assertEqual(
            got["captured"], ["20260715900769"],
            "rcept_no가 캡션으로 승격된 표에서는 공시 원문 패널을 열 "
            "방법이 없습니다 — 캡션 값 자체가 클릭 가능해야 합니다",
        )

    def test_no_rcept_no_field_means_nothing_is_clickable(self):
        """rcept_no가 아예 없는 표에서는 아무 셀도 클릭 가능해선 안 된다 —
        확인되지 않은 다른 필드(공시 제목 등)를 추측해 클릭 가능하게
        만들면 안 된다는 계약의 반대쪽 확인이다."""
        got = run_doc_click('[{corp_name:"엔켐",n:1},{corp_name:"엔켐",n:2}]')
        self.assertEqual(got["captured"], [])


@unittest.skipUnless(_NODE, "node가 없어 ui.js의 실제 클릭 배선을 검증할 수 없습니다")
class TestDocPanelClickReachesServerRoute(unittest.TestCase):
    """openDocPanel에 넘어가는 클릭 값이 실제로 se_server가 라우팅하는
    값인지를 검증한다.

    위 TestDocPanelClickWiring은 "docListRow/레코드에 넣은 값이
    openDocPanel에 그대로 나오는가"만 봤다 — 자기 자신과의 일치라서 그
    값 자체가 서버가 거부하는 형태(`doc:` 접두어가 남은 접수번호 등)여도
    통과했다. 실제 사고: 본문의 doc: 섹션을 목록 하나로 모으면서
    (addDocListEntry) `doc:<접수번호>` 섹션 키가 docListRow의 rcept_no로
    그대로 새어 들어갈 뻔했고, 그 값이 그대로 openDocPanel →
    `/api/se/disclosure/doc%3A...` 요청으로 이어져 라우터(router.py)의
    `[0-9]{8,20}` 패턴과 매칭되지 않아 404가 났다(프로덕션 실측).

    여기서는 se_server.api.router.match를 실제로 import해, 클릭이 만든
    값으로 GET /api/se/disclosure/<값>이 실제로 라우팅되는지 그 자체를
    확인한다 — 문자열을 하드코딩해 비교하면 서버 패턴이 바뀔 때 이
    테스트도 같이 놓친다.
    """

    @staticmethod
    def _routes_to_disclosure(value):
        """value로 만든 공시 원문 요청 경로가 실제 라우터를 통과하면
        True. ui.js의 openDocPanel이 그대로 쓰는
        `"/api/se/disclosure/" + encodeURIComponent(rceptNo)` 조합과
        같은 인코딩(quote)을 쓴다."""
        from urllib.parse import quote

        from se_server.api.router import match

        result = match("GET", "/api/se/disclosure/" + quote(str(value), safe=""))
        return (
            result is not None
            and result[0] == "disclosure"
            and result[1].get("rcept_no") == str(value)
        )

    def test_doc_prefixed_value_does_not_route(self):
        """이 테스트 스위트의 전제 확인: "doc:" 접두어가 남은 값은 실제로
        라우터가 거부한다(수정 전 실측 404의 직접 원인). 이 검증이 없으면
        아래 통과 테스트들이 애초에 무엇을 막는지 근거가 없다.
        """
        self.assertFalse(self._routes_to_disclosure("doc:20260715900769"))

    def test_route_1_doc_list_row_click_reaches_disclosure_route(self):
        """경로 ①: 공시 원문 목록(doc_list) 행 클릭.

        서버가 실제로 만드는 섹션 키 형식(`doc:<rcept_no>`,
        se_server/jobs/runner.py의 expand_stage2 `f"doc:{rcept_no}"`)에서
        시작해 docKeyRceptNo → docListRow → tableLayout → tableEl → 클릭
        까지 실제 ui.js 배선 그대로 재현한다.
        """
        rcept_no = "20260715900769"
        row = run_js(
            'docListRow(docKeyRceptNo(' + json.dumps(f"doc:{rcept_no}") + '),'
            ' {char_count: 1, truncated: false,'
            '  main_file: "20260715900769.xml", files: ["20260715900769.xml"]})'
        )
        self.assertEqual(row["rcept_no"], rcept_no)
        got = run_doc_click(json.dumps([row]))
        self.assertEqual(got["captured"], [rcept_no])
        self.assertTrue(
            self._routes_to_disclosure(got["captured"][0]),
            f"공시 원문 목록 클릭 값 {got['captured'][0]!r}이 서버 라우터를 통과하지 못합니다",
        )

    def test_route_2_disclosures_table_rcept_no_column_reaches_disclosure_route(self):
        """경로 ②: `disclosures` 표(Stage1, 행마다 접수번호가 달라 표 본문
        열로 남는 일반적인 경우)의 rcept_no 열 클릭. 이 경로는 원래
        접두어가 없어 정상 동작했지만, 값 자체가 서버 계약을 지키는지는
        지금까지 검증한 적이 없었다.
        """
        rows = [
            {"rcept_dt": "20260710", "rcept_no": "20260710000123", "report_nm": "A"},
            {"rcept_dt": "20260715", "rcept_no": "20260715900769", "report_nm": "B"},
        ]
        got = run_doc_click(json.dumps(rows))
        self.assertEqual(got["orientation"], "horizontal")
        self.assertEqual(len(got["captured"]), 2)
        for value in got["captured"]:
            self.assertTrue(
                self._routes_to_disclosure(value),
                f"disclosures 표 클릭 값 {value!r}이 서버 라우터를 통과하지 못합니다",
            )

    def test_route_3_caption_promoted_rcept_no_reaches_disclosure_route(self):
        """경로 ③: rcept_no가 모든 행에서 같아(affiliates·financials 실측)
        캡션으로 승격된 경우의 클릭.
        """
        rows = [
            {"rcept_no": "20260715900769", "corp_name": "엔켐", "inv_prm": "A"},
            {"rcept_no": "20260715900769", "corp_name": "엔켐", "inv_prm": "B"},
        ]
        got = run_doc_click(json.dumps(rows))
        caption_keys = [c["key"] for c in got["caption"]]
        self.assertIn("rcept_no", caption_keys,
                     "이 테스트 자체가 재현하려는 전제(rcept_no가 캡션으로 승격됨)가 깨졌습니다")
        self.assertEqual(got["captured"], ["20260715900769"])
        self.assertTrue(
            self._routes_to_disclosure(got["captured"][0]),
            f"캡션 승격 클릭 값 {got['captured'][0]!r}이 서버 라우터를 통과하지 못합니다",
        )


@unittest.skipUnless(_NODE, "node가 없어 ui.js의 실제 렌더 결과를 검증할 수 없습니다")
class TestAmountCellTitleTooltip(unittest.TestCase):
    """리뷰 지적 ⑤: 억·조 단위로 줄인 금액(예: 1,308,239,417 → "13.1억")은
    정확한 원 단위 값을 화면 어디서도 볼 수 없었다. AMOUNT_FIELDS(app.js)
    열의 셀에 title(마우스 오버) 속성으로 원본 값을 남기는지를 실제 렌더
    결과로 확인한다.
    """

    def test_horizontal_amount_cell_carries_raw_value_as_title(self):
        got = run_doc_click('[{plan_amount:1308239417,n:1},{plan_amount:4500,n:2}]')
        titled = {c["text"]: c["title"] for c in got["cells"] if c["title"]}
        self.assertEqual(titled.get("13.1억"), "1308239417")
        self.assertEqual(titled.get("4,500"), "4500")

    def test_vertical_amount_cell_carries_raw_value_as_title(self):
        got = run_doc_click('[{plan_amount:1308239417}]')
        titled = {c["text"]: c["title"] for c in got["cells"] if c["title"]}
        self.assertEqual(titled.get("13.1억"), "1308239417")

    def test_non_amount_field_gets_no_title(self):
        """AMOUNT_FIELDS가 아닌 열에 title을 붙이면 툴팁이 무의미하게
        남발된다 — 값이 큰 수라도(예: n) 붙지 않아야 한다."""
        got = run_doc_click('[{n:1308239417,n2:1},{n:1,n2:2}]')
        self.assertTrue(all(c["title"] is None for c in got["cells"]))

    def test_label_column_in_vertical_table_gets_no_title(self):
        """세로 표의 라벨 칸("계획 금액")은 값 칸이 아니다 — title이 붙으면
        안 된다."""
        got = run_doc_click('[{plan_amount:1308239417}]')
        label_cells = [c for c in got["cells"] if c["text"] == "계획 금액"]
        self.assertTrue(label_cells)
        self.assertTrue(all(c["title"] is None for c in label_cells))


# ── 펼치기(⋯) 버튼 클릭 배선 재현용 가짜 DOM ────────────────────────────
#
# tableLayout()이 계산만 하고 ui.js가 실제로 그리지 않으면(또는 버튼이
# innerHTML로 데이터를 섞어 넣으면) "접힌 열이 사라지지 않는다"는 계약이
# 화면에서는 지켜지지 않는다 — _DOC_CLICK_HARNESS와 같은 이유로 실제 클릭
# 이벤트를 재현해 확인한다. tbody 자식은 [데이터행0, 상세행0, 데이터행1,
# 상세행1, ...] 순서로 쌓인다(ui.js tableEl 참고 — 상세 행을 각 데이터
# 행 직후에 바로 append하기 때문).
_FOLD_CLICK_HARNESS = r"""
const vm = require("vm");
const fs = require("fs");

class FakeEl {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this._text = "";
    this._className = "";
    this._listeners = {};
  }
  appendChild(c) { this.children.push(c); return c; }
  insertRow() { const tr = new FakeEl("tr"); this.appendChild(tr); return tr; }
  insertCell() { const td = new FakeEl("td"); this.appendChild(td); return td; }
  createTHead() { const el = new FakeEl("thead"); this.appendChild(el); return el; }
  createTBody() { const el = new FakeEl("tbody"); this.appendChild(el); return el; }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  dispatch(type) { (this._listeners[type] || []).forEach(function (fn) { fn({}); }); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text; }
  set className(v) { this._className = v; }
  get className() { return this._className; }
}

function findByTag(node, tag, out) {
  out = out || [];
  if (!node) return out;
  if (node.tag === tag) out.push(node);
  (node.children || []).forEach(function (c) { findByTag(c, tag, out); });
  return out;
}

// 실제 브라우저의 textContent는 하위 텍스트 노드를 전부 이어붙인다 — 이
// 가짜 DOM은 setter로 지정한 값만 저장하므로(appendChild로 쌓은 자식은
// 반영 안 함), 접힌 상세 칸처럼 자식을 이어붙여 만든 노드는 직접 순회해야
// 실제로 화면에 뭐가 찍히는지 알 수 있다.
function textOf(node) {
  if (!node) return "";
  if (!node.children || node.children.length === 0) return node.textContent || "";
  return node.children.map(textOf).join("");
}

const sandbox = {
  console: console,
  document: {
    createElement: function (tag) { return new FakeEl(tag); },
    createDocumentFragment: function () { return new FakeEl("#fragment"); },
    createTextNode: function (t) { const n = new FakeEl("#text"); n.textContent = t; return n; },
    addEventListener: function () {},
    getElementById: function () { return null; },
  },
  localStorage: {
    getItem: function () { return null; },
    setItem: function () {},
    removeItem: function () {},
  },
  fetch: function () { return Promise.reject(new Error("no network in test")); },
};
vm.createContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[1], "utf-8"), { filename: "app.js" }).runInContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[2], "utf-8"), { filename: "ui.js" }).runInContext(sandbox);

const records = %(records)s;
const table = sandbox.tableLayout(records);
const frag = sandbox.tableEl(table);

const tbody = findByTag(frag, "tbody", [])[0];
const rows = (tbody && tbody.children) || [];
const dataRows = rows.filter(function (_, i) { return i %% 2 === 0; });
const detailRows = rows.filter(function (_, i) { return i %% 2 === 1; });
const buttons = findByTag(frag, "button", []);

const before = detailRows.map(function (r) { return { hidden: !!r.hidden, text: textOf(r) }; });
buttons.forEach(function (b) { b.dispatch("click"); });
const after = detailRows.map(function (r) { return { hidden: !!r.hidden, text: textOf(r) }; });

process.stdout.write(JSON.stringify({
  foldedKeys: table.foldedKeys,
  buttonCount: buttons.length,
  buttonTexts: buttons.map(function (b) { return textOf(b); }),
  dataRowCount: dataRows.length,
  before: before,
  after: after,
}));
"""


def run_fold_click(records_js: str):
    """records_js를 tableLayout → tableEl로 그린 뒤, class="fold-btn" 버튼을
    실제로 클릭해 상세 행의 hidden 상태·내용이 어떻게 바뀌는지 돌려준다.
    """
    script = _FOLD_CLICK_HARNESS % {"records": records_js}
    out = subprocess.run(
        [_NODE, "-e", script, str(_APP), str(_UI)],
        capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode != 0:
        raise AssertionError(f"node 실행 실패:\n{out.stderr}")
    return json.loads(out.stdout)


@unittest.skipUnless(_NODE, "node가 없어 ui.js의 실제 렌더 결과를 검증할 수 없습니다")
class TestFoldButtonWiring(unittest.TestCase):
    """Step 4: insider_timeline처럼 12열을 넘는 표에서 "나머지 N개 열"
    버튼이 실제로 그려지고, 클릭하면 접힌 값이 실제로 나타나는지 확인한다.
    tableLayout()이 foldedKeys·foldedRows를 계산만 하고 ui.js가 그리지
    않으면(또는 클릭이 배선되지 않으면) 사용자는 여전히 데이터를 볼 방법이
    없다 — 계산 결과 검증(TestWideTableFolding)만으로는 이 배선 유실을
    못 잡는다.
    """

    _WIDE = ("Array.from({length:2},(_,i)=>Object.fromEntries("
              "Array.from({length:20},(_,j)=>['f'+j, i+'-'+j])))")

    def test_button_appears_once_per_row_with_folded_count(self):
        got = run_fold_click(self._WIDE)
        self.assertEqual(got["buttonCount"], got["dataRowCount"])
        for text in got["buttonTexts"]:
            self.assertEqual(text, f"나머지 {len(got['foldedKeys'])}개 열")

    def test_detail_row_starts_hidden(self):
        """접힌 값은 클릭 전까지는 화면을 어지럽히면 안 된다."""
        got = run_fold_click(self._WIDE)
        self.assertTrue(all(b["hidden"] for b in got["before"]))

    def test_click_reveals_the_hidden_columns_values(self):
        """접는 것이지 없애는 것이 아니다 — 클릭하면 실제로 값이 보여야
        한다."""
        got = run_fold_click(self._WIDE)
        self.assertTrue(all(not a["hidden"] for a in got["after"]),
                         "클릭해도 상세 행이 계속 숨겨져 있습니다")
        self.assertIn("f12: 0-12", got["after"][0]["text"],
                       "접힌 첫 열(f12)의 값이 펼친 화면에 없습니다")
        self.assertIn("f19: 0-19", got["after"][0]["text"],
                       "접힌 마지막 열(f19)의 값이 펼친 화면에 없습니다")

    def test_narrow_table_has_no_fold_button(self):
        """12열 이하는 접을 게 없으니 버튼도 없어야 한다 — 빈 접기 UI를
        남발하면 그 자체가 소음이다."""
        got = run_fold_click('[{a:1,b:2},{a:3,b:4}]')
        self.assertEqual(got["buttonCount"], 0)

    def test_essential_column_not_duplicated_in_the_folded_panel(self):
        """rcept_no는 splitVisibleFolded가 항상 visible에 남기므로
        foldedKeys에는 나오지 않아야 한다 — 펼친 패널에 다시 나타나면
        같은 값이 두 군데(본문 열 + 펼친 패널)에 중복 표기된다."""
        wide_with_rcept_no = (
            "Array.from({length:2},(_,i)=>Object.assign("
            "Object.fromEntries(Array.from({length:20},(_,j)=>['f'+j, i+'-'+j])),"
            "{rcept_no: '2026010100000'+i}))"
        )
        got = run_fold_click(wide_with_rcept_no)
        self.assertNotIn("rcept_no", got["foldedKeys"])
        for a in got["after"]:
            self.assertNotIn("접수번호", a["text"])


# ── 테마 토글 실제 동작 재현용 가짜 DOM ────────────────────────────────
#
# test_se_page_assets.py의 test_theme_toggle_is_wired_not_dead는 init()의
# 소스 문자열에 "theme"가 있는지만 본다(login/logout 등 기존 단순 버튼과
# 같은 수준의 정적 확인). 여기서는 그 버튼을 눌렀을 때 실제로 동작하는
# 엔진(applyTheme/toggleTheme)을 tableEl·renderSection과 같은 방식으로
# node vm에서 직접 실행해, <html data-theme>·버튼 문구·localStorage
# 저장까지 실제로 바뀌는지 확인한다.
_THEME_HARNESS = r"""
const vm = require("vm");
const fs = require("fs");

class FakeEl {
  constructor(tag) {
    this.tag = tag;
    this._text = "";
    this._attrs = {};
  }
  setAttribute(k, v) { this._attrs[k] = String(v); }
  getAttribute(k) {
    return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null;
  }
  set textContent(v) { this._text = String(v); }
  get textContent() { return this._text; }
}

const documentElement = new FakeEl("html");
const themeBtn = new FakeEl("button");
const STORE = {};

const sandbox = {
  console: console,
  document: {
    documentElement: documentElement,
    createElement: function (tag) { return new FakeEl(tag); },
    getElementById: function (id) { return id === "theme-toggle" ? themeBtn : null; },
    // ui.js 맨 아래 document.addEventListener("DOMContentLoaded", init)이
    // 파일을 로드하는 시점에 바로 실행된다 — 이 스텁이 없으면 하네스가
    // 테마 함수를 부르기도 전에 로드 자체가 TypeError로 실패한다.
    addEventListener: function () {},
  },
  localStorage: {
    getItem: function (k) {
      return Object.prototype.hasOwnProperty.call(STORE, k) ? STORE[k] : null;
    },
    setItem: function (k, v) { STORE[k] = String(v); },
    removeItem: function (k) { delete STORE[k]; },
  },
};
vm.createContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[1], "utf-8"), { filename: "app.js" }).runInContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[2], "utf-8"), { filename: "ui.js" }).runInContext(sandbox);

// sandbox.LS_THEME는 여기서 못 읽는다 — app.js가 top-level const로
// 선언한 값은 vm 컨텍스트의 전역 프로퍼티로 노출되지 않는다(함수 선언과
// 달리 const/let 바인딩은 그 스크립트 안에서만 보인다). app.js가
// "se_theme"로 고정해 두므로(LS_THEME 정의 참고) 여기서도 그 문자열
// 그대로 STORE를 읽는다.
const steps = [];
function snapshot() {
  steps.push({
    attr: documentElement.getAttribute("data-theme"),
    btnText: themeBtn.textContent,
    stored: STORE["se_theme"] === undefined ? null : STORE["se_theme"],
  });
}

sandbox.applyTheme(sandbox.localStorage.getItem("se_theme") === "light" ? "light" : "dark");
snapshot(); // init()이 페이지를 열 때 하는 것과 같은 최초 적용 — 저장된 값이 없으니 다크
sandbox.toggleTheme(); // 버튼 클릭 1회
snapshot();
sandbox.toggleTheme(); // 버튼 클릭 2회 — 다시 다크로 돌아와야 한다
snapshot();

process.stdout.write(JSON.stringify({ steps: steps }));
"""


def run_theme_toggle():
    out = subprocess.run(
        [_NODE, "-e", _THEME_HARNESS, str(_APP), str(_UI)],
        capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode != 0:
        raise AssertionError(f"node 실행 실패:\n{out.stderr}")
    return json.loads(out.stdout)["steps"]


@unittest.skipUnless(_NODE, "node가 없어 ui.js의 실제 테마 전환을 검증할 수 없습니다")
class TestThemeToggleEngine(unittest.TestCase):
    """applyTheme/toggleTheme(ui.js)를 실제로 실행해 <html data-theme>·
    버튼 문구·localStorage 저장이 함께 바뀌는지 확인한다. 정적 검사
    (test_theme_toggle_is_wired_not_dead)는 init()이 이 함수들을 부르는지만
    보므로, 함수 자체가 옳게 동작하는지는 이쪽에서 확인해야 한다."""

    def test_default_start_is_dark_with_explicit_attribute(self):
        """data-theme는 "생략"이 아니라 "dark"로 명시적으로 붙는다 —
        applyTheme()가 항상 setAttribute를 호출하기 때문이다(속성이
        없어도 다크로 보이는 게 아니라, 애초에 속성이 항상 있다)."""
        steps = run_theme_toggle()
        self.assertEqual(steps[0]["attr"], "dark")
        self.assertEqual(steps[0]["btnText"], "라이트 모드")

    def test_first_toggle_switches_to_light_and_persists(self):
        steps = run_theme_toggle()
        self.assertEqual(steps[1]["attr"], "light")
        self.assertEqual(steps[1]["btnText"], "다크 모드")
        self.assertEqual(steps[1]["stored"], "light",
                         "선택이 localStorage(se_theme)에 저장되지 않습니다")

    def test_second_toggle_switches_back_to_dark_and_persists(self):
        steps = run_theme_toggle()
        self.assertEqual(steps[2]["attr"], "dark")
        self.assertEqual(steps[2]["btnText"], "라이트 모드")
        self.assertEqual(steps[2]["stored"], "dark")


# ── 목차·2단 넓은 표 클래스 실제 동작 재현용 가짜 DOM ──────────────────
#
# _RENDER_SECTION_HARNESS를 확장해 #toc 엘리먼트를 등록해 둔다 —
# groupHolder/sectionHolder는 document.getElementById("toc")가 null이면
# 조용히 건너뛰므로(다른 렌더 테스트들이 그 경로로 통과한다), 목차가
# 실제로 채워지는지는 #toc가 있는 이 하네스에서만 확인할 수 있다. 표
# orientation에 따라 감싸는 .sec에 "wide"가 붙는지도 함께 본다 —
# renderSection()이 실제로 그 판단을 하는 지점이다.
_TOC_AND_WIDE_HARNESS = r"""
const vm = require("vm");
const fs = require("fs");

const ELEMENTS = Object.create(null);

class FakeEl {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this._text = "";
    this._className = "";
    this._id = "";
    this.dataset = {};
    this._listeners = {};
  }
  appendChild(c) { this.children.push(c); return c; }
  insertBefore(node, ref) {
    const idx = ref ? this.children.indexOf(ref) : -1;
    if (idx === -1) this.children.push(node);
    else this.children.splice(idx, 0, node);
    return node;
  }
  removeChild(c) {
    const idx = this.children.indexOf(c);
    if (idx !== -1) this.children.splice(idx, 1);
    return c;
  }
  insertRow() { const tr = new FakeEl("tr"); this.appendChild(tr); return tr; }
  insertCell() { const td = new FakeEl("td"); this.appendChild(td); return td; }
  createTHead() { const el = new FakeEl("thead"); this.appendChild(el); return el; }
  createTBody() { const el = new FakeEl("tbody"); this.appendChild(el); return el; }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  dispatch(type) { (this._listeners[type] || []).forEach(function (fn) { fn({}); }); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text; }
  set className(v) { this._className = v; }
  get className() { return this._className; }
  set id(v) { this._id = v; ELEMENTS[v] = this; }
  get id() { return this._id; }
}

const bodyEl = new FakeEl("div");
bodyEl.id = "body";
const tocEl = new FakeEl("nav");
tocEl.id = "toc";

function collectTocTexts(node, out) {
  out = out || [];
  if (!node) return out;
  if ((node.className || "").indexOf("toc-item") !== -1) out.push(node.textContent);
  (node.children || []).forEach(function (c) { collectTocTexts(c, out); });
  return out;
}

// wrap(class="sec"[ wide])은 h2를 첫 자식으로 둔 div다 — sectionHolder가
// id를 붙이는 건 안쪽 holder뿐이라 wrap 자체는 id로 못 찾는다(ui.js가
// parentNode에 기대지 않는 이유와 같다 — 이 가짜 DOM은 parentNode를
// 구현하지 않는다). h2 텍스트로 어느 섹션의 wrap인지 구분한다.
function collectSecWraps(node, out) {
  out = out || [];
  if (!node) return out;
  if (node.tag === "div" && node.children[0] && node.children[0].tag === "h2") {
    out.push({ h2: node.children[0].textContent, className: node.className });
  }
  (node.children || []).forEach(function (c) { collectSecWraps(c, out); });
  return out;
}

const sandbox = {
  console: console,
  document: {
    createElement: function (tag) { return new FakeEl(tag); },
    createDocumentFragment: function () { return new FakeEl("#fragment"); },
    createTextNode: function (t) { const n = new FakeEl("#text"); n.textContent = t; return n; },
    addEventListener: function () {},
    getElementById: function (id) { return ELEMENTS[id] || null; },
  },
  localStorage: {
    getItem: function () { return null; },
    setItem: function () {},
    removeItem: function () {},
  },
  fetch: function () { return Promise.reject(new Error("no network in test")); },
};
vm.createContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[1], "utf-8"), { filename: "app.js" }).runInContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[2], "utf-8"), { filename: "ui.js" }).runInContext(sandbox);

sandbox.openDocPanel = function () {};
// fund_usage(자금 그룹) — 레코드 2건 → 가로(여러 행) 표 → "wide"가 붙어야 한다.
sandbox.renderSection("fund_usage", [{ a: 1, b: 2 }, { a: 3, b: 4 }]);
// financials(재무 그룹) — 레코드 1건(평면 객체) → 세로 표 → "wide"가 붙으면 안 된다.
sandbox.renderSection("financials", { a: 1, b: 2 });

process.stdout.write(JSON.stringify({
  tocTexts: collectTocTexts(tocEl, []),
  wraps: collectSecWraps(bodyEl, []),
}));
"""


def run_toc_and_wide():
    out = subprocess.run(
        [_NODE, "-e", _TOC_AND_WIDE_HARNESS, str(_APP), str(_UI)],
        capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode != 0:
        raise AssertionError(f"node 실행 실패:\n{out.stderr}")
    return json.loads(out.stdout)


@unittest.skipUnless(_NODE, "node가 없어 ui.js의 실제 렌더 결과를 검증할 수 없습니다")
class TestTocAndWideTableWiring(unittest.TestCase):
    """목차가 실제로 채워지는지, 가로 표가 있는 섹션만 2단 폭 전체를 쓰는
    "wide" 클래스를 받는지를 renderSection()의 실제 결과 DOM으로 확인한다.
    """

    def test_toc_gets_group_and_section_entries(self):
        got = run_toc_and_wide()
        self.assertIn("자금", got["tocTexts"], "그룹(자금) 목차 항목이 없습니다")
        self.assertIn("재무", got["tocTexts"], "그룹(재무) 목차 항목이 없습니다")
        self.assertIn("자금 사용 내역", got["tocTexts"], "섹션 목차 항목이 없습니다")
        self.assertIn("재무제표", got["tocTexts"], "섹션 목차 항목이 없습니다")

    def test_horizontal_table_section_gets_wide_class(self):
        got = run_toc_and_wide()
        wrap = next(w for w in got["wraps"] if w["h2"] == "자금 사용 내역")
        self.assertEqual(wrap["className"], "sec wide")

    def test_vertical_table_section_does_not_get_wide_class(self):
        got = run_toc_and_wide()
        wrap = next(w for w in got["wraps"] if w["h2"] == "재무제표")
        self.assertEqual(wrap["className"], "sec")


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestDocumentBlocks(unittest.TestCase):
    """공시 원문(우측 패널)을 문단·표 블록으로 나누는 documentBlocks() 검증.

    지금은 원문이 <pre> 한 덩어리라, 원본이 담고 있는 `항목 | 값 | 값`
    파이프 구분 표가 그대로 한 줄로 이어져 읽을 수 없다. dart_client.py의
    _html_to_structured_text를 실제로 확인한 결과(_table_to_markdown이
    행마다 "\\n"으로 join) — 표 행은 줄바꿈으로 구분된다(두산 골든
    tests/fixtures/sample_outputs/두산_doc_20260422800615.txt 실측: 매 행이
    "| ... |" 형태로 한 줄씩 나온다). documentBlocks는 그 구조를 복원할
    뿐 요약하거나 판정하지 않는다(v0.8.5 원칙).
    """

    def test_pipe_rows_become_a_table_block(self):
        got = run_js(r'documentBlocks("머리말\n| 항목 | 값 |\n| 자본금 | 100 |\n꼬리말")')
        kinds = [b["kind"] for b in got]
        self.assertIn("table", kinds)

    def test_prose_around_tables_is_kept(self):
        got = run_js(r'documentBlocks("머리말\n| a | b |\n꼬리말")')
        texts = " ".join(b.get("text", "") for b in got if b["kind"] == "text")
        self.assertIn("머리말", texts)
        self.assertIn("꼬리말", texts)

    def test_nothing_is_lost(self):
        src = "가나다\n| ㄱ | ㄴ |\n라마바"
        got = run_js(f'documentBlocks({json.dumps(src)})')
        joined = "".join(
            b.get("text", "") + " ".join(" ".join(r) for r in b.get("rows", []))
            for b in got
        )
        for token in ("가나다", "ㄱ", "ㄴ", "라마바"):
            self.assertIn(token, joined, f"{token}이 사라졌습니다")

    def test_plain_text_without_pipes_is_one_text_block(self):
        got = run_js('documentBlocks("파이프 없는 본문")')
        self.assertEqual([b["kind"] for b in got], ["text"])

    def test_empty_input_is_empty_list(self):
        for expr in ('documentBlocks("")', "documentBlocks(null)"):
            self.assertEqual(run_js(expr), [])

    def test_separator_only_rows_are_not_data(self):
        """`|---|---|` 는 구분선이지 데이터가 아니다."""
        got = run_js(r'documentBlocks("| a | b |\n|---|---|\n| 1 | 2 |")')
        table = [b for b in got if b["kind"] == "table"][0]
        self.assertNotIn(["---", "---"], table["rows"])

    def test_markdown_heading_hash_is_stripped_from_prose(self):
        """Minor 5(리뷰 지적): dart_client.py의 _html_to_structured_text가
        <h1>~<h6>를 "#" * level + " " 마크다운 헤더로 바꾼다(구조 보존용
        중간 표현) — 이 화면은 마크다운을 렌더링하지 않고 <p>에 textContent
        로 그대로 보여주므로, 그 표시를 그대로 두면 "### 회사합병 결정"처럼
        원문(HTML)에는 없던 기호가 사용자에게 그대로 노출된다. 제목
        내용(텍스트)은 그대로 두고 마크다운 기호만 벗겨야 한다."""
        got = run_js(r'documentBlocks("## 회사합병 결정\n본문 문단")')
        texts = " ".join(b.get("text", "") for b in got if b["kind"] == "text")
        self.assertIn("회사합병 결정", texts, "제목 내용이 사라졌습니다")
        self.assertNotIn("#", texts, "마크다운 헤더 기호(#)가 그대로 노출됩니다")

    def test_markdown_heading_hash_stripped_for_all_levels(self):
        for level in range(1, 7):
            hashes = "#" * level
            got = run_js(f'documentBlocks({json.dumps(hashes + " 제목" + str(level))})')
            texts = " ".join(b.get("text", "") for b in got if b["kind"] == "text")
            self.assertIn(f"제목{level}", texts)
            self.assertNotIn("#", texts, f"레벨 {level} 헤더의 #이 남아 있습니다")

    def test_hash_not_followed_by_space_is_left_alone(self):
        """마크다운 헤더 문법(# + 공백)이 아닌, 우연히 #으로 시작하는 본문
        (예: "#1233 관련")까지 지우면 원문을 훼손한다 — 헤더 패턴이 아니면
        건드리지 않는다."""
        got = run_js(r'documentBlocks("#1233 관련 안건")')
        texts = " ".join(b.get("text", "") for b in got if b["kind"] == "text")
        self.assertIn("#1233 관련 안건", texts)

    def test_real_world_flattened_pipes_lose_nothing(self):
        """사장님이 실제로 붙여넣은 엔켐 회사합병 결정 공시 조각 — 행 구분이
        (붙여넣는 과정에서였는지) 줄바꿈 없이 공백만으로 이어져 있었다.
        정상 경로(골든 파일 실측 — 두산_doc_20260422800615.txt)는 표 행마다
        줄바꿈이 있지만, 이렇게 무너진 입력이 와도 토큰 하나 잃으면 안
        된다(문단·표 어느 쪽으로 분류되는지는 이 테스트의 관심사가 아니다
        — "사라지지 않는다"만 확인한다).
        """
        src = (
            "엔켐/회사합병 결정(종속회사의 주요경영사항) /(2026.07.15)회사합병 결정 "
            "종속회사인 | Enchem America Inc. | 의 주요경영사항 신고 | "
            "|---|---| "
            "| 1. 합병방법 | Enchem America Inc.가 THE GROWHUB LIMITED의 자회사인 | "
            "| 5. 합병신주의 종류와 수(주) | 보통주식 | - | "
            "| 종류주식 | - |"
        )
        got = run_js(f'documentBlocks({json.dumps(src)})')
        joined = "".join(
            b.get("text", "") + " " + " ".join(" ".join(r) for r in b.get("rows", []))
            for b in got
        )
        for token in (
            "엔켐/회사합병 결정(종속회사의 주요경영사항)",
            "Enchem America Inc.",
            "의 주요경영사항 신고",
            "1. 합병방법",
            "THE GROWHUB LIMITED",
            "5. 합병신주의 종류와 수(주)",
            "보통주식",
            "종류주식",
        ):
            self.assertIn(token, joined, f"{token}이 사라졌습니다")


# ── 공시 원문 패널 실제 렌더 재현용 가짜 DOM ────────────────────────────
#
# documentBlocks() 단독 테스트(TestDocumentBlocks)로는 openDocPanel이 그
# 결과를 실제로 그리는지 확인할 수 없다 — "정의만 있고 부르는 곳이 없는"
# 사고가 이 화면에서 이미 네 번 났다(브리프). 인증(token())·네트워크
# (fetch)는 이 태스크의 관심사가 아니므로 둘 다 스텁으로 바꾸고,
# openDocPanel을 실제로 실행해 #panel-body 안에 <table>·<p>가 실제로
# 생기는지(문자열 검사가 아니라 렌더 결과로) 확인한다.
_DOC_PANEL_HARNESS = r"""
const vm = require("vm");
const fs = require("fs");

const ELEMENTS = Object.create(null);

class FakeEl {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this._text = "";
    this._className = "";
    this._id = "";
    this.classList = { add: function () {}, remove: function () {} };
  }
  appendChild(c) { this.children.push(c); return c; }
  insertRow() { const tr = new FakeEl("tr"); this.appendChild(tr); return tr; }
  insertCell() { const td = new FakeEl("td"); this.appendChild(td); return td; }
  createTHead() { const el = new FakeEl("thead"); this.appendChild(el); return el; }
  createTBody() { const el = new FakeEl("tbody"); this.appendChild(el); return el; }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text; }
  set className(v) { this._className = v; }
  get className() { return this._className; }
  set id(v) { this._id = v; ELEMENTS[v] = this; }
  get id() { return this._id; }
}

const panelBody = new FakeEl("div");
panelBody.id = "panel-body";
const panel = new FakeEl("aside");
panel.id = "panel";

function collectTags(node, out) {
  out = out || [];
  if (!node) return out;
  out.push(node.tag);
  (node.children || []).forEach(function (c) { collectTags(c, out); });
  return out;
}

function collectCells(node, out) {
  out = out || [];
  if (!node) return out;
  if (node.tag === "td") out.push(node.textContent);
  (node.children || []).forEach(function (c) { collectCells(c, out); });
  return out;
}

function flattenText(node) {
  if (!node) return "";
  if (!node.children || node.children.length === 0) return node.textContent || "";
  return node.children.map(flattenText).join(" ");
}

const sandbox = {
  console: console,
  document: {
    createElement: function (tag) { return new FakeEl(tag); },
    createDocumentFragment: function () { return new FakeEl("#fragment"); },
    createTextNode: function (t) { const n = new FakeEl("#text"); n.textContent = t; return n; },
    addEventListener: function () {},
    getElementById: function (id) { return ELEMENTS[id] || null; },
  },
  localStorage: {
    getItem: function () { return null; },
    setItem: function () {},
    removeItem: function () {},
  },
  fetch: function () { return Promise.reject(new Error("no network in test")); },
};
vm.createContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[1], "utf-8"), { filename: "app.js" }).runInContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[2], "utf-8"), { filename: "ui.js" }).runInContext(sandbox);

// 인증·네트워크는 이 태스크의 관심사가 아니다 — openDocPanel이 실제로
// 그리는 DOM만 본다. openDocPanel 스파이 교체(위 _DOC_CLICK_HARNESS)와
// 같은 이유로, top-level function 선언은(let/const와 달리) vm 컨텍스트
// 전역에 노출되므로 이렇게 덮어쓸 수 있다.
sandbox.token = async function () { return "fake-token"; };
sandbox.fetch = function () {
  return Promise.resolve({
    status: 200,
    json: async function () { return %(body)s; },
  });
};

(async function () {
  await sandbox.openDocPanel("20260715900769");
  process.stdout.write(JSON.stringify({
    tags: collectTags(panelBody, []),
    cellTexts: collectCells(panelBody, []),
    flat: flattenText(panelBody),
  }));
})();
"""


def run_doc_panel(body_js: str):
    """body_js(서버가 돌려주는 JSON 응답 리터럴)로 openDocPanel을 실제로
    실행해, #panel-body에 실제로 그려진 태그 목록·표 셀 텍스트·전체 텍스트를
    돌려준다.
    """
    script = _DOC_PANEL_HARNESS % {"body": body_js}
    out = subprocess.run(
        [_NODE, "-e", script, str(_APP), str(_UI)],
        capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode != 0:
        raise AssertionError(f"node 실행 실패:\n{out.stderr}")
    return json.loads(out.stdout)


@unittest.skipUnless(_NODE, "node가 없어 ui.js의 실제 렌더 결과를 검증할 수 없습니다")
class TestDocPanelRendersDocumentBlocks(unittest.TestCase):
    """openDocPanel이 documentBlocks()를 실제로 불러 그리는지 확인한다.

    documentBlocks 정의만 있고 openDocPanel 호출부가 안 바뀌면 화면은
    여전히 <pre> 한 덩어리다 — "정의만 있고 부르는 곳이 없는" 사고가 이
    화면에서 이미 네 번 났다(브리프 지적). 여기서는 실제로 함수를 실행해
    #panel-body 안에 <table>·<p>가 생기는지, 표 셀이 실제로 나뉘는지 본다.
    """

    _BODY = json.dumps({
        "text": "머리말\n| 항목 | 값 |\n|---|---|\n| 자본금 | 100 |\n꼬리말",
        "truncated": False,
        "char_count": 20,
    }, ensure_ascii=False)

    def test_table_and_paragraph_tags_are_actually_rendered(self):
        got = run_doc_panel(self._BODY)
        self.assertIn("table", got["tags"],
                       "표가 <table>로 그려지지 않습니다 — documentBlocks가 "
                       "배선되지 않았을 수 있습니다")
        self.assertIn("p", got["tags"],
                       "문단이 <p>로 그려지지 않습니다")

    def test_table_cells_are_split_not_one_blob(self):
        got = run_doc_panel(self._BODY)
        self.assertIn("자본금", got["cellTexts"])
        self.assertIn("100", got["cellTexts"])
        # 구분선("---")은 데이터가 아니다 — 셀로 남으면 안 된다.
        self.assertNotIn("---", got["cellTexts"])

    def test_nothing_is_lost_in_the_rendered_panel(self):
        got = run_doc_panel(self._BODY)
        for token in ("머리말", "자본금", "100", "꼬리말"):
            self.assertIn(token, got["flat"], f"{token}이 화면에서 사라졌습니다")

    def test_truncated_note_still_appears(self):
        body = json.dumps({
            "text": "본문",
            "truncated": True,
            "char_count": 12345,
        }, ensure_ascii=False)
        got = run_doc_panel(body)
        self.assertIn("12,345자 중 일부입니다", got["flat"])


# ── doc: 섹션 본문 목록 통합(ui.js의 addDocListEntry) ──────────────────
#
# 원인: documentBlocks(파이프를 표로 복원)는 openDocPanel(우측 패널)에만
# 쓰이고, 본문의 doc: 섹션은 여전히 {title:"본문", text: 수천 자}로 그대로
# 나갔다(엔켐 실측 34건 × 약 13만 자). 승인된 수정 방향: 본문에서는 doc:
# 원문 전체를 걷어내고 "어떤 공시를 가져왔는지" 목록 하나만 남긴다 —
# 원문은 접수번호를 클릭해 우측 패널에서 본다.
#
# 여기서는 app.js·ui.js를 실제로 같은 vm 컨텍스트에서 실행해(문자열 검사가
# 아니라) addDocListEntry를 여러 번 불렀을 때 h2가 하나만 생기는지, 그리고
# 목록의 각 행을 실제로 클릭하면 openDocPanel이 정확한 접수번호로 불리는지
# 확인한다 — "정의만 있고 호출부가 안 바뀐" 사고가 이 프로젝트에서 이미
# 여러 번 났다(브리프 지적).
_DOC_LIST_HARNESS = r"""
const vm = require("vm");
const fs = require("fs");

const ELEMENTS = Object.create(null);

class FakeEl {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this._text = "";
    this._className = "";
    this._id = "";
    this.dataset = {};
    this._listeners = {};
  }
  appendChild(c) { this.children.push(c); return c; }
  insertBefore(node, ref) {
    const idx = ref ? this.children.indexOf(ref) : -1;
    if (idx === -1) this.children.push(node);
    else this.children.splice(idx, 0, node);
    return node;
  }
  removeChild(c) {
    const idx = this.children.indexOf(c);
    if (idx !== -1) this.children.splice(idx, 1);
    return c;
  }
  get firstChild() { return this.children.length ? this.children[0] : null; }
  insertRow() { const tr = new FakeEl("tr"); this.appendChild(tr); return tr; }
  insertCell() { const td = new FakeEl("td"); this.appendChild(td); return td; }
  createTHead() { const el = new FakeEl("thead"); this.appendChild(el); return el; }
  createTBody() { const el = new FakeEl("tbody"); this.appendChild(el); return el; }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  dispatch(type) { (this._listeners[type] || []).forEach(function (fn) { fn({}); }); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text; }
  set className(v) { this._className = v; }
  get className() { return this._className; }
  set id(v) { this._id = v; ELEMENTS[v] = this; }
  get id() { return this._id; }
}

const bodyEl = new FakeEl("div");
bodyEl.id = "body";

function collectByTag(node, tag, out) {
  out = out || [];
  if (!node) return out;
  if (node.tag === tag) out.push(node);
  (node.children || []).forEach(function (c) { collectByTag(c, tag, out); });
  return out;
}

function collectDocEls(node, out) {
  out = out || [];
  if (!node) return out;
  if (node.className === "doc") out.push(node);
  (node.children || []).forEach(function (c) { collectDocEls(c, out); });
  return out;
}

const sandbox = {
  console: console,
  document: {
    createElement: function (tag) { return new FakeEl(tag); },
    createDocumentFragment: function () { return new FakeEl("#fragment"); },
    createTextNode: function (t) { const n = new FakeEl("#text"); n.textContent = t; return n; },
    addEventListener: function () {},
    getElementById: function (id) { return ELEMENTS[id] || null; },
  },
  localStorage: {
    getItem: function () { return null; },
    setItem: function () {},
    removeItem: function () {},
  },
  fetch: function () { return Promise.reject(new Error("no network in test")); },
};
vm.createContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[1], "utf-8"), { filename: "app.js" }).runInContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[2], "utf-8"), { filename: "ui.js" }).runInContext(sandbox);

const CAPTURED = [];
sandbox.openDocPanel = function (rceptNo) { CAPTURED.push(rceptNo); };

const entries = %(entries)s;
entries.forEach(function (e) { sandbox.addDocListEntry(e.rcept_no, e.value); });

const h2s = collectByTag(bodyEl, "h2", []);
const docEls = collectDocEls(bodyEl, []);
docEls.forEach(function (e) { e.dispatch("click"); });

process.stdout.write(JSON.stringify({
  h2Texts: h2s.map(function (h) { return h.textContent; }),
  docCellCount: docEls.length,
  captured: CAPTURED,
}));
"""


def run_doc_list(entries_js: str):
    script = _DOC_LIST_HARNESS % {"entries": entries_js}
    out = subprocess.run(
        [_NODE, "-e", script, str(_APP), str(_UI)],
        capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode != 0:
        raise AssertionError(f"node 실행 실패:\n{out.stderr}")
    return json.loads(out.stdout)


@unittest.skipUnless(_NODE, "node가 없어 ui.js의 실제 목록 렌더링을 검증할 수 없습니다")
class TestDocListConsolidation(unittest.TestCase):
    """doc:<접수번호> 섹션이 도착할 때마다 새 h2로 원문 전체를 쏟아내던
    문제(엔켐 실측 34건 × 약 13만 자)의 수정 — 본문에는 "어떤 공시를
    가져왔는지" 목록 하나만 남고, 각 행에서 우측 패널을 열 수 있어야 한다
    (그러지 않으면 원문을 볼 방법이 사라져 진짜로 숨기는 게 된다).
    """

    _ENTRIES = json.dumps([
        {"rcept_no": "20260715900769",
         "value": {"text": "엔켐/회사합병 결정" + ("가" * 3900),
                    "char_count": 3988, "truncated": False}},
        {"rcept_no": "20260708900785",
         "value": {"text": "엔켐/전환사채" + ("나" * 1600),
                    "char_count": 1676, "truncated": False}},
        {"rcept_no": "20260123000072",
         "value": {"text": "", "char_count": 0, "truncated": False}},
    ], ensure_ascii=False)

    def test_all_entries_collapse_into_a_single_titled_section(self):
        got = run_doc_list(self._ENTRIES)
        matches = [t for t in got["h2Texts"] if t == "공시 원문 목록"]
        self.assertEqual(
            len(matches), 1,
            f"doc: 섹션이 여러 개의 h2로 흩어졌거나 목록 자체가 없습니다 "
            f"(h2: {got['h2Texts']})",
        )

    def test_every_entry_is_clickable_and_opens_its_own_doc_panel(self):
        got = run_doc_list(self._ENTRIES)
        self.assertEqual(got["docCellCount"], 3, "목록 행 수만큼 클릭 가능한 셀이 없습니다")
        self.assertEqual(
            sorted(got["captured"]),
            sorted(["20260715900769", "20260708900785", "20260123000072"]),
            "목록 항목을 클릭해도 우측 패널(openDocPanel)이 열리지 않습니다",
        )

    _ENTRIES_WITH_MAIN_FILE = json.dumps([
        {"rcept_no": "20260715900769",
         "value": {"text": "엔켐/회사합병 결정" + ("가" * 3900),
                    "char_count": 3988, "truncated": False,
                    "main_file": "20260715900769.xml",
                    "files": ["20260715900769.xml"]}},
        {"rcept_no": "20260708900785",
         "value": {"text": "엔켐/전환사채" + ("나" * 1600),
                    "char_count": 1676, "truncated": False,
                    "main_file": "20260708900785.xml",
                    "files": ["20260708900785.xml"]}},
        # ZIP 수신 실패 사례(files=[]) — 리뷰 지적 ④.
        {"rcept_no": "20260123000072",
         "value": {"text": "", "char_count": 0, "truncated": False,
                    "main_file": "", "files": []}},
    ], ensure_ascii=False)

    def test_rcept_no_click_path_survives_adding_main_file_and_files_columns(self):
        """리뷰 지적 ①로 main_file·files 열을 표에 추가하면 열 순서가
        바뀐다 — rcept_no 클릭 배선(tableEl의 table.keys.indexOf("rcept_no"))이
        키로 열을 찾는지, 고정된 열 위치를 가정하는지를 여기서 실제로
        검증한다. 셀 인덱스가 밀려 배선이 끊기면 이 테스트가 잡는다."""
        got = run_doc_list(self._ENTRIES_WITH_MAIN_FILE)
        self.assertEqual(got["docCellCount"], 3,
                         "main_file·files 열이 추가되며 클릭 가능한 셀 수가 달라졌습니다")
        self.assertEqual(
            sorted(got["captured"]),
            sorted(["20260715900769", "20260708900785", "20260123000072"]),
            "main_file·files 열 추가 후 우측 패널 클릭 경로가 끊겼습니다",
        )


# 위 _DOC_LIST_HARNESS는 addDocListEntry만 재현한다 — showGate()·
# renderHeadPlaceholder()가 실제로 DOC_LIST_ROWS를 비우는지는 그 두 함수가
# 참조하는 #gate·#main·#panel 등 추가 DOM이 필요해 별도 하네스로 확인한다
# (브리프 제약: "showGate()가 패널·#body 등을 비우는 성질을 깨뜨리지
# 말 것 — 새로 만드는 목록도 이 정리에 포함돼야 한다").
_DOC_LIST_RESET_HARNESS = r"""
const vm = require("vm");
const fs = require("fs");

const ELEMENTS = Object.create(null);

class FakeClassList {
  constructor() { this._set = new Set(); }
  add(c) { this._set.add(c); }
  remove(c) { this._set.delete(c); }
  contains(c) { return this._set.has(c); }
}

// 실제 브라우저의 document.getElementById()는 문서(연결된 트리)에서만
// 찾는다 — 노드를 removeChild로 떼어내면 그 id는 더 이상 찾히지 않는다.
// 이 하네스의 ELEMENTS는 한 번 등록되면 지워지지 않는 평평한 사전이라
// 그 성질을 흉내 내지 못하면(떼어낸 뒤에도 여전히 찾힌다), showGate()
// 이후 sectionHolder()/groupHolder()가 실제로는 새 노드를 만들어야 할
// 자리에서 여전히 붙어 있는 것처럼 착각한 옛(분리된) 노드를 재사용해
// buggy하지 않은 실제 동작을 buggy한 것처럼 오검출한다 — removeChild에서
// 떼어낸 서브트리 전체의 id를 여기서 지워 실제 DOM과 같은 성질을 맞춘다.
function deregister(node) {
  if (!node) return;
  if (node._id) delete ELEMENTS[node._id];
  (node.children || []).forEach(deregister);
}

class FakeEl {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this._text = "";
    this._className = "";
    this._id = "";
    this.dataset = {};
    this._listeners = {};
    this.hidden = false;
    this.classList = new FakeClassList();
  }
  appendChild(c) { this.children.push(c); return c; }
  insertBefore(node, ref) {
    const idx = ref ? this.children.indexOf(ref) : -1;
    if (idx === -1) this.children.push(node);
    else this.children.splice(idx, 0, node);
    return node;
  }
  removeChild(c) {
    const idx = this.children.indexOf(c);
    if (idx !== -1) this.children.splice(idx, 1);
    deregister(c);
    return c;
  }
  get firstChild() { return this.children.length ? this.children[0] : null; }
  insertRow() { const tr = new FakeEl("tr"); this.appendChild(tr); return tr; }
  insertCell() { const td = new FakeEl("td"); this.appendChild(td); return td; }
  createTHead() { const el = new FakeEl("thead"); this.appendChild(el); return el; }
  createTBody() { const el = new FakeEl("tbody"); this.appendChild(el); return el; }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  dispatch(type) { (this._listeners[type] || []).forEach(function (fn) { fn({}); }); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text; }
  set className(v) { this._className = v; }
  get className() { return this._className; }
  set id(v) { this._id = v; ELEMENTS[v] = this; }
  get id() { return this._id; }
}

function makeEl(tag, id) {
  const el = new FakeEl(tag);
  if (id) el.id = id;
  return el;
}

const bodyEl = makeEl("div", "body");
makeEl("nav", "toc");
makeEl("div", "company-info");
makeEl("section", "gate");
makeEl("main", "main");
makeEl("p", "gate-msg");
makeEl("aside", "panel");
makeEl("div", "panel-body");
makeEl("span", "head-name");
makeEl("div", "bar");
makeEl("button", "actor-btn");

function collectDocEls(node, out) {
  out = out || [];
  if (!node) return out;
  if (node.className === "doc") out.push(node);
  (node.children || []).forEach(function (c) { collectDocEls(c, out); });
  return out;
}

const sandbox = {
  console: console,
  document: {
    createElement: function (tag) { return new FakeEl(tag); },
    createDocumentFragment: function () { return new FakeEl("#fragment"); },
    createTextNode: function (t) { const n = new FakeEl("#text"); n.textContent = t; return n; },
    addEventListener: function () {},
    getElementById: function (id) { return ELEMENTS[id] || null; },
  },
  localStorage: {
    getItem: function () { return null; },
    setItem: function () {},
    removeItem: function () {},
  },
  fetch: function () { return Promise.reject(new Error("no network in test")); },
};
vm.createContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[1], "utf-8"), { filename: "app.js" }).runInContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[2], "utf-8"), { filename: "ui.js" }).runInContext(sandbox);

sandbox.openDocPanel = function () {};

sandbox.addDocListEntry("1", { text: "a", char_count: 1, truncated: false });
sandbox.addDocListEntry("2", { text: "b", char_count: 1, truncated: false });
const beforeReset = collectDocEls(bodyEl, []).length;

%(reset_call)s;

sandbox.addDocListEntry("3", { text: "c", char_count: 1, truncated: false });
const afterReset = collectDocEls(bodyEl, []).length;

process.stdout.write(JSON.stringify({ beforeReset: beforeReset, afterReset: afterReset }));
"""


def run_doc_list_reset(reset_call: str):
    script = _DOC_LIST_RESET_HARNESS % {"reset_call": reset_call}
    out = subprocess.run(
        [_NODE, "-e", script, str(_APP), str(_UI)],
        capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode != 0:
        raise AssertionError(f"node 실행 실패:\n{out.stderr}")
    return json.loads(out.stdout)


@unittest.skipUnless(_NODE, "node가 없어 ui.js의 실제 렌더 결과를 검증할 수 없습니다")
class TestDocListResetsWithShowGateAndPlaceholder(unittest.TestCase):
    """showGate()·renderHeadPlaceholder()가 패널·#body·헤더 등을 비우는
    성질(브리프 제약)에 이 새 목록(DOC_LIST_ROWS)도 포함돼야 한다 — 안
    그러면 로그아웃 후 다음 사용자가, 또는 새 회사를 분석한 사용자가
    이전 회사의 공시 목록 행이 이어붙은 화면을 보게 된다.
    """

    def test_show_gate_starts_a_fresh_doc_list(self):
        got = run_doc_list_reset("sandbox.showGate()")
        self.assertEqual(got["beforeReset"], 2)
        self.assertEqual(
            got["afterReset"], 1,
            "showGate() 이후에도 이전 목록 행이 새 목록에 남아 있습니다",
        )

    def test_render_head_placeholder_starts_a_fresh_doc_list(self):
        got = run_doc_list_reset('sandbox.renderHeadPlaceholder("새 회사")')
        self.assertEqual(
            got["afterReset"], 1,
            "renderHeadPlaceholder() 이후에도 이전 목록 행이 남아 있습니다",
        )


# ── #body(그리드)와 .sec 사이 DOM 중간 요소가 전부 display:contents인지 ──
#
# 리뷰가 잡은 사고: .grp{display:contents}만으로는 부족했다. groupHolder()가
# .grp(section) 안에 중간 홀더 div(id="grp-<제목>")를 하나 더 만들고
# sectionHolder()가 .sec을 그 홀더에 붙이는데, 그 홀더는 display:contents가
# 아니었다 — 그러면 #body 그리드의 직속 아이템은 h1과 그 홀더 박스가 되고
# .sec은 홀더 안의 평범한 블록 자식일 뿐이라 그리드 아이템이 아니게 된다.
# .sec.wide{grid-column:1/-1}이 완전히 무효화돼, 넓힌 표가 그리드 1칸
# 폭으로 도로 좁아졌다 — 그런데도 기존 두 검사
# (test_horizontal_table_section_gets_wide_class는 wrap.className만,
# test_toc_and_two_column_grid_exist는 HTML에 "grid-template-columns"
# 문자열이 있는지만 봐서) 둘 다 초록이었다.
#
# 정적 문자열 검사로는 이 사고를 못 잡는다(클래스 이름이 있다는 것과 그
# 클래스가 실제로 그 요소에 붙어 있다는 것, 그리고 그 요소가 실제로 #body와
# .sec 사이에 낀 중간 노드라는 것은 서로 다른 사실이다). 그래서 이 검사는
# renderSection()을 실제로 실행해(node vm, 위 _RENDER_SECTION_HARNESS와
# 같은 방식) #body부터 각 .sec까지의 DOM 조상 사슬을 그대로 수집하고,
# index.html의 CSS를 파싱해 각 조상 클래스가 실제로 display:contents
# 규칙을 갖는지 대조한다. 중간에 하나라도 빠지면 실패한다.
_SEC_ANCESTORS_HARNESS = r"""
const vm = require("vm");
const fs = require("fs");

const ELEMENTS = Object.create(null);

class FakeEl {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this._text = "";
    this._className = "";
    this._id = "";
    this.dataset = {};
    this._listeners = {};
  }
  appendChild(c) { this.children.push(c); return c; }
  insertBefore(node, ref) {
    const idx = ref ? this.children.indexOf(ref) : -1;
    if (idx === -1) this.children.push(node);
    else this.children.splice(idx, 0, node);
    return node;
  }
  removeChild(c) {
    const idx = this.children.indexOf(c);
    if (idx !== -1) this.children.splice(idx, 1);
    return c;
  }
  insertRow() { const tr = new FakeEl("tr"); this.appendChild(tr); return tr; }
  insertCell() { const td = new FakeEl("td"); this.appendChild(td); return td; }
  createTHead() { const el = new FakeEl("thead"); this.appendChild(el); return el; }
  createTBody() { const el = new FakeEl("tbody"); this.appendChild(el); return el; }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  dispatch(type) { (this._listeners[type] || []).forEach(function (fn) { fn({}); }); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text; }
  set className(v) { this._className = v; }
  get className() { return this._className; }
  set id(v) { this._id = v; ELEMENTS[v] = this; }
  get id() { return this._id; }
}

const bodyEl = new FakeEl("div");
bodyEl.id = "body";

// #body의 자식들에서 시작해 .sec(첫 자식이 h2인 div)에 도달할 때까지
// 내려가며, .sec 자신은 뺀 "그 사이" 조상만 기록한다. ancestors는 각
// 단계에서 "지금 서 있는 노드"를 append한 뒤 자식으로 내려가므로, #body
// 자신(시작점)은 절대 ancestors에 섞이지 않는다.
function collectSecAncestors(node, ancestors, out) {
  ancestors = ancestors || [];
  out = out || [];
  if (!node) return out;
  const isSec = node.tag === "div" && node.children[0] && node.children[0].tag === "h2";
  if (isSec) {
    out.push({ h2: node.children[0].textContent, ancestors: ancestors.slice() });
    return out;
  }
  const nextAncestors = ancestors.concat([{ tag: node.tag, className: node.className || "" }]);
  (node.children || []).forEach(function (c) { collectSecAncestors(c, nextAncestors, out); });
  return out;
}

const sandbox = {
  console: console,
  document: {
    createElement: function (tag) { return new FakeEl(tag); },
    createDocumentFragment: function () { return new FakeEl("#fragment"); },
    createTextNode: function (t) { const n = new FakeEl("#text"); n.textContent = t; return n; },
    addEventListener: function () {},
    getElementById: function (id) { return ELEMENTS[id] || null; },
  },
  localStorage: {
    getItem: function () { return null; },
    setItem: function () {},
    removeItem: function () {},
  },
  fetch: function () { return Promise.reject(new Error("no network in test")); },
};
vm.createContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[1], "utf-8"), { filename: "app.js" }).runInContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[2], "utf-8"), { filename: "ui.js" }).runInContext(sandbox);

sandbox.openDocPanel = function () {};
// 서로 다른 그룹(자금·재무)에 각각 표 하나씩 — 그룹 홀더가 여러 개
// 만들어지는 일반적인 경우를 재현한다.
sandbox.renderSection("fund_usage", [{ a: 1, b: 2 }, { a: 3, b: 4 }]);
sandbox.renderSection("financials", { a: 1, b: 2 });

const paths = [];
bodyEl.children.forEach(function (c) { collectSecAncestors(c, [], paths); });

process.stdout.write(JSON.stringify({ paths: paths }));
"""


def run_sec_ancestors():
    out = subprocess.run(
        [_NODE, "-e", _SEC_ANCESTORS_HARNESS, str(_APP), str(_UI)],
        capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode != 0:
        raise AssertionError(f"node 실행 실패:\n{out.stderr}")
    return json.loads(out.stdout)["paths"]


def _display_contents_classes(html: str) -> set:
    """index.html CSS에서 `display:contents`가 걸린 단일 클래스 선택자
    이름을 모은다(`.a,.b{...}`처럼 콤마로 묶인 선택자 목록도 각각
    분리해 인식한다). 이 저장소의 관련 규칙은 전부 단순 클래스
    선택자라 이 정도로 충분하다."""
    classes = set()
    for m in re.finditer(r"([.\w,\s>-]+)\{([^}]*)\}", html):
        selector, body = m.group(1), m.group(2)
        if not re.search(r"display\s*:\s*contents", body):
            continue
        for part in selector.split(","):
            part = part.strip()
            if re.fullmatch(r"\.[A-Za-z0-9_-]+", part):
                classes.add(part[1:])
    return classes


@unittest.skipUnless(_NODE, "node가 없어 ui.js의 실제 DOM 중첩을 검증할 수 없습니다")
class TestSectionIsAnActualGridItem(unittest.TestCase):
    """#body(그리드 컨테이너)와 .sec 사이에 낀 모든 중간 요소가
    display:contents가 아니면, .sec은 그리드의 직속 아이템이 아니게 되어
    .sec.wide{grid-column:1/-1}이 무효화된다. 이 검사는 실제 DOM 조상
    사슬(node vm)과 실제 CSS 규칙(index.html 파싱)을 대조해, 하나라도
    빠지면 실패한다 — 클래스 이름이나 grid-template-columns 문자열의
    존재 여부만 보는 정적 검사로는 이 사고를 잡지 못했다(리뷰 지적).
    """

    def test_every_ancestor_between_body_and_sec_is_display_contents(self):
        html = (_ROOT / "docs" / "tool" / "se" / "index.html").read_text(encoding="utf-8")
        contents_classes = _display_contents_classes(html)
        self.assertTrue(
            contents_classes,
            "index.html에서 display:contents 클래스를 하나도 찾지 못했습니다 — "
            "검사 자체가 무의미해집니다",
        )

        paths = run_sec_ancestors()
        self.assertTrue(paths, ".sec 엘리먼트를 하나도 찾지 못했습니다")

        offenders = []
        for entry in paths:
            for anc in entry["ancestors"]:
                classes = (anc["className"] or "").split()
                if not any(c in contents_classes for c in classes):
                    offenders.append(
                        f'{entry["h2"]!r} 섹션의 조상 <{anc["tag"]} class="{anc["className"]}">'
                        f'가 display:contents가 아닙니다'
                    )
        self.assertEqual(
            offenders, [],
            "#body와 .sec 사이에 display:contents가 아닌 중간 요소가 있습니다 — "
            ".sec이 그리드의 직속 아이템이 되지 못해 .sec.wide가 무효화됩니다:\n  "
            + "\n  ".join(offenders),
        )


# ── 목차 순서·클릭·active 강조·resetToc 실제 동작 재현용 가짜 DOM ───────
#
# 리뷰 지적 ①·②: 목차는 groupHolder()의 insertBefore 순서 대신 무조건
# appendChild로 쌓여, company_info(STAGE1_SPECS 첫 항목이라 항상 먼저
# 도착)가 매번 목차 맨 위를 차지했지만 화면(#body)에서는 groupOrderIndex가
# 가장 커서 맨 아래였다. 그리고 "목차 클릭 → scrollIntoView", "active
# 강조", "showGate/renderHeadPlaceholder의 resetToc() 호출"은 문자열
# 존재만 확인하는 정적 검사로 지켜지고 있었는데, 뮤테이션으로 실제
# 확인한 결과 이 세 가지는 그런 정적 검사조차 없어 관련 코드를 지워도
# 아무 테스트도 실패하지 않았다.
#
# 이 하네스는 #toc·#body·#company-info·#gate·#main·#panel 등 showGate·
# renderHeadPlaceholder·renderCompanyInfo·renderSection이 실제로 참조하는
# 엘리먼트를 전부 등록하고, IntersectionObserver도 흉내 내(node에는 원래
# 없다) TOC_OBSERVER 콜백을 직접 호출할 수 있게 한다.
_TOC_BEHAVIOR_HARNESS = r"""
const vm = require("vm");
const fs = require("fs");

const ELEMENTS = Object.create(null);
const SCROLLS = [];
let OBSERVE_CALLS = [];
let OBSERVER_CALLBACK = null;
let DISCONNECT_COUNT = 0;

function titleOf(node) {
  if (!node || !node.children || !node.children[0]) return "";
  const first = node.children[0];
  if (first.tag === "h1" || first.tag === "h2") return first.textContent;
  return "";
}

class FakeClassList {
  constructor() { this._set = new Set(); }
  add(c) { this._set.add(c); }
  remove(c) { this._set.delete(c); }
  contains(c) { return this._set.has(c); }
}

class FakeIntersectionObserver {
  constructor(cb) { OBSERVER_CALLBACK = cb; }
  observe(el) { OBSERVE_CALLS.push(el); }
  disconnect() { DISCONNECT_COUNT += 1; OBSERVE_CALLS = []; }
}

class FakeEl {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this._text = "";
    this._className = "";
    this._id = "";
    this.dataset = {};
    this._listeners = {};
    this.hidden = false;
    this.classList = new FakeClassList();
  }
  appendChild(c) { this.children.push(c); return c; }
  insertBefore(node, ref) {
    const idx = ref ? this.children.indexOf(ref) : -1;
    if (idx === -1) this.children.push(node);
    else this.children.splice(idx, 0, node);
    return node;
  }
  removeChild(c) {
    const idx = this.children.indexOf(c);
    if (idx !== -1) this.children.splice(idx, 1);
    return c;
  }
  get firstChild() { return this.children.length ? this.children[0] : null; }
  insertRow() { const tr = new FakeEl("tr"); this.appendChild(tr); return tr; }
  insertCell() { const td = new FakeEl("td"); this.appendChild(td); return td; }
  createTHead() { const el = new FakeEl("thead"); this.appendChild(el); return el; }
  createTBody() { const el = new FakeEl("tbody"); this.appendChild(el); return el; }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  dispatch(type) { (this._listeners[type] || []).forEach(function (fn) { fn({}); }); }
  scrollIntoView(opts) { SCROLLS.push({ title: titleOf(this), opts: opts }); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text; }
  set className(v) { this._className = v; }
  get className() { return this._className; }
  set id(v) { this._id = v; ELEMENTS[v] = this; }
  get id() { return this._id; }
}

function makeEl(tag, id) {
  const el = new FakeEl(tag);
  if (id) el.id = id;
  return el;
}

const bodyEl = makeEl("div", "body");
const tocEl = makeEl("nav", "toc");
const companyInfoEl = makeEl("div", "company-info");
makeEl("section", "gate");
makeEl("main", "main");
makeEl("p", "gate-msg");
makeEl("aside", "panel");
makeEl("div", "panel-body");
makeEl("span", "head-name");
makeEl("div", "bar");
makeEl("button", "actor-btn");

function tocLinkTexts() {
  return tocEl.children.map(function (c) { return c.textContent; });
}

const sandbox = {
  console: console,
  IntersectionObserver: FakeIntersectionObserver,
  document: {
    createElement: function (tag) { return new FakeEl(tag); },
    createDocumentFragment: function () { return new FakeEl("#fragment"); },
    createTextNode: function (t) { const n = new FakeEl("#text"); n.textContent = t; return n; },
    addEventListener: function () {},
    getElementById: function (id) { return ELEMENTS[id] || null; },
  },
  localStorage: {
    getItem: function () { return null; },
    setItem: function () {},
    removeItem: function () {},
  },
  fetch: function () { return Promise.reject(new Error("no network in test")); },
};
vm.createContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[1], "utf-8"), { filename: "app.js" }).runInContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[2], "utf-8"), { filename: "ui.js" }).runInContext(sandbox);

sandbox.openDocPanel = function () {};

// 1) company_info(헤더)가 실측대로 가장 먼저 도착한다(STAGE1_SPECS 첫 항목).
sandbox.renderCompanyInfo({ ceo_nm: "홍길동" });
// 2) "감사·부실"(groupOrderIndex 3) 섹션이 "자금"(groupOrderIndex 0)보다
//    먼저 도착한다 — 폴링 응답 순서는 서버가 준 순서라 그룹 정의 순서를
//    보장하지 않는다. 목차가 도착 순서 그대로 쌓이면(이전 버전의 버그)
//    "감사·부실"이 "자금"보다 앞에 남는다.
sandbox.renderSection("distress", [{ a: 1 }]);
sandbox.renderSection("fund_usage", [{ a: 1 }, { a: 2 }]);

const orderAfterRender = tocLinkTexts();

// 클릭 배선 — 목차 항목을 실제로 클릭해 scrollIntoView가 그 항목이
// 가리키는 대상(targetEl)에서 호출되는지 확인한다.
tocEl.children.forEach(function (c) { c.dispatch("click"); });
const scrollTitles = SCROLLS.map(function (s) { return s.title; });

// active 강조 — IntersectionObserver 콜백을 직접 흉내 내 company_info
// 박스가 화면에 보이는 상태로 들어왔다고 알린 뒤, 그 목차 링크에 active가
// 붙는지/사라지는지 확인한다.
const firstLink = tocEl.children[0];
OBSERVER_CALLBACK([{ target: companyInfoEl, isIntersecting: true }]);
const activeWhileVisible = firstLink.classList.contains("active");
OBSERVER_CALLBACK([{ target: companyInfoEl, isIntersecting: false }]);
const activeAfterLeaving = firstLink.classList.contains("active");

// showGate — 목차·company-info·body가 실제로 비는지, 옵저버가 disconnect
// 되는지 확인한다.
sandbox.showGate("메시지");
const afterShowGate = {
  tocCount: tocEl.children.length,
  companyInfoCount: companyInfoEl.children.length,
  bodyCount: bodyEl.children.length,
  disconnectCount: DISCONNECT_COUNT,
};

// 다시 채운 뒤 renderHeadPlaceholder로도 같은 성질을 확인한다.
sandbox.renderCompanyInfo({ ceo_nm: "홍길동" });
sandbox.renderSection("fund_usage", [{ a: 1 }, { a: 2 }]);
sandbox.renderHeadPlaceholder("새 회사");
const afterPlaceholder = {
  tocCount: tocEl.children.length,
  companyInfoCount: companyInfoEl.children.length,
  bodyCount: bodyEl.children.length,
};

process.stdout.write(JSON.stringify({
  orderAfterRender: orderAfterRender,
  scrollTitles: scrollTitles,
  activeWhileVisible: activeWhileVisible,
  activeAfterLeaving: activeAfterLeaving,
  afterShowGate: afterShowGate,
  afterPlaceholder: afterPlaceholder,
}));
"""


def run_toc_behavior():
    out = subprocess.run(
        [_NODE, "-e", _TOC_BEHAVIOR_HARNESS, str(_APP), str(_UI)],
        capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode != 0:
        raise AssertionError(f"node 실행 실패:\n{out.stderr}")
    return json.loads(out.stdout)


@unittest.skipUnless(_NODE, "node가 없어 ui.js의 실제 목차 동작을 검증할 수 없습니다")
class TestTocMatchesScreenOrderAndBehavesOnInteraction(unittest.TestCase):
    """리뷰 지적 ①(High)·②의 행동 검사 부분(목차 클릭·active 강조·
    resetToc 호출)을 실제 렌더·클릭·옵저버 콜백으로 확인한다.
    """

    def test_toc_order_matches_document_order_not_arrival_order(self):
        """company_info가 항상 먼저 도착해도(실측), 화면(#body)에서는
        groupOrderIndex가 가장 커서 맨 아래에 있다 — 목차도 그 순서를
        따라야 한다. "감사·부실"이 "자금"보다 먼저 도착해도 최종 목차
        에서는 "자금"이 앞에 와야 한다(groupOrderIndex 순서)."""
        got = run_toc_behavior()
        self.assertEqual(
            got["orderAfterRender"],
            ["기업 개요", "자금", "자금 사용 내역", "감사·부실", "부실 징후"],
            "목차 순서가 화면(DOM) 순서와 다릅니다",
        )

    def test_clicking_each_toc_item_scrolls_to_its_own_target(self):
        got = run_toc_behavior()
        self.assertEqual(
            got["scrollTitles"], got["orderAfterRender"],
            "목차 항목을 클릭해도 해당 섹션으로 스크롤되지 않습니다 — "
            "scrollIntoView 배선이 없거나 엉뚱한 대상을 가리킵니다",
        )

    def test_intersecting_section_gets_active_class_and_loses_it_on_leave(self):
        got = run_toc_behavior()
        self.assertTrue(got["activeWhileVisible"],
                        "섹션이 화면에 들어와도 목차 링크에 active가 붙지 않습니다")
        self.assertFalse(got["activeAfterLeaving"],
                         "섹션이 화면을 벗어나도 active가 그대로 남아 있습니다")

    def test_show_gate_empties_toc_company_info_and_body_and_disconnects_observer(self):
        got = run_toc_behavior()
        after = got["afterShowGate"]
        self.assertEqual(after["tocCount"], 0,
                         "showGate() 이후에도 목차 항목이 남아 있습니다 — 죽은 링크가 됩니다")
        self.assertEqual(after["companyInfoCount"], 0,
                         "showGate() 이후에도 기업 개요 박스에 내용이 남아 있습니다")
        self.assertEqual(after["bodyCount"], 0,
                         "showGate() 이후에도 본문(#body)에 섹션이 남아 있습니다")
        self.assertGreaterEqual(after["disconnectCount"], 1,
                                "showGate()가 IntersectionObserver를 disconnect하지 않습니다")

    def test_render_head_placeholder_also_empties_toc_and_company_info(self):
        got = run_toc_behavior()
        after = got["afterPlaceholder"]
        self.assertEqual(after["tocCount"], 0,
                         "renderHeadPlaceholder() 이후에도 이전 회사의 목차 항목이 "
                         "남아 있습니다")
        self.assertEqual(after["companyInfoCount"], 0,
                         "renderHeadPlaceholder() 이후에도 이전 회사의 기업 개요가 "
                         "남아 있습니다")
        self.assertEqual(after["bodyCount"], 0,
                         "renderHeadPlaceholder() 이후에도 이전 회사의 본문 섹션이 "
                         "남아 있습니다")


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestChartData(unittest.TestCase):
    # rcept_dt는 하이픈 있는 "2026-04-15"(10자) 형태다 — 엔켐 실측
    # (field-inventory)이 그렇다. 브리프가 예시로 준 "20260415"(8자,
    # 하이픈 없음)는 프로덕션에 존재하지 않는 형태였다(리뷰 지적 ④).
    _INSIDER = """[
      {source:"elestock", repror:"오정강", rcept_dt:"2026-03-04", sp_stock_lmp_rate:"14.13"},
      {source:"elestock", repror:"오정강", rcept_dt:"2026-03-27", sp_stock_lmp_rate:"3.60"},
      {source:"elestock", repror:"와이어트그룹", rcept_dt:"2026-04-15", sp_stock_lmp_rate:"6.53"}
    ]"""

    def test_groups_into_one_dataset_per_reporter(self):
        got = run_js(f'chartData({self._INSIDER}, CHART_SPECS.insider_timeline)')
        labels = sorted(d["label"] for d in got["datasets"])
        self.assertEqual(labels, ["오정강", "와이어트그룹"])

    def test_x_labels_are_sorted_by_date(self):
        got = run_js(f'chartData({self._INSIDER}, CHART_SPECS.insider_timeline)')
        self.assertEqual(got["labels"], ["2026.03.04", "2026.03.27", "2026.04.15"])

    def test_series_aligns_values_to_the_shared_x_axis(self):
        """계열마다 관측 시점이 다르다. 없는 지점은 null이어야 선이 끊긴다 —
        0으로 채우면 지분이 0이 됐다는 거짓말이 된다."""
        got = run_js(f'chartData({self._INSIDER}, CHART_SPECS.insider_timeline)')
        ohj = next(d for d in got["datasets"] if d["label"] == "오정강")
        self.assertEqual(ohj["data"], [14.13, 3.6, None])

    def test_zero_is_a_real_value_not_a_gap(self):
        got = run_js('''chartData([
          {repror:"김", rcept_dt:"2026-01-01", sp_stock_lmp_rate:"0"},
          {repror:"김", rcept_dt:"2026-01-02", sp_stock_lmp_rate:"1.5"}
        ], CHART_SPECS.insider_timeline)''')
        self.assertEqual(got["datasets"][0]["data"], [0, 1.5])

    def test_non_numeric_value_becomes_a_gap_not_zero(self):
        got = run_js('''chartData([
          {repror:"김", rcept_dt:"2026-01-01", sp_stock_lmp_rate:"-"},
          {repror:"김", rcept_dt:"2026-01-02", sp_stock_lmp_rate:"1.5"}
        ], CHART_SPECS.insider_timeline)''')
        self.assertEqual(got["datasets"][0]["data"], [None, 1.5])

    def test_comma_separated_number_is_parsed(self):
        got = run_js('''chartData([{tm:"제1회", plan_amount:"13,082,000,000",
                        real_dtls_amount:"13,082,000,000"}], CHART_SPECS.fund_usage)''')
        self.assertEqual(got["datasets"][0]["data"], [13082000000])

    def test_plan_vs_actual_makes_two_datasets(self):
        got = run_js('''chartData([{tm:"제1회", plan_amount:"100", real_dtls_amount:"80"}],
                        CHART_SPECS.fund_usage)''')
        self.assertEqual([d["label"] for d in got["datasets"]], ["계획 금액", "실제 집행 금액"])

    def test_numeric_x_axis_sorts_numerically_not_lexically(self):
        """회차 10이 9보다 앞에 오면 그래프가 거짓말을 한다.

        tm은 순수 숫자 문자열이 아니라 "제9회"·"제10회"처럼 한글이 섞인
        실측(field-inventory) 형태다 — numeric()은 이 값에서 실패하므로
        (전체가 숫자가 아니다) 내장된 숫자만 뽑아 비교해야 한다.
        """
        got = run_js('''chartData([
          {tm:"제9회",  plan_amount:"1", real_dtls_amount:"1"},
          {tm:"제10회", plan_amount:"2", real_dtls_amount:"2"}
        ], CHART_SPECS.fund_usage)''')
        self.assertEqual(got["labels"], ["제9회", "제10회"])

    def test_round_numbers_with_korean_suffix_sort_correctly_even_out_of_order(self):
        """리뷰 지적 ①의 정확한 재현: 응답 순서가 "제10회", "제14회",
        "제9회"(사전식으로 이미 뒤섞인 순서)로 와도 회차 순서(9→10→14)로
        정렬돼야 한다."""
        got = run_js('''chartData([
          {tm:"제10회", plan_amount:"1", real_dtls_amount:"1"},
          {tm:"제14회", plan_amount:"2", real_dtls_amount:"2"},
          {tm:"제9회",  plan_amount:"3", real_dtls_amount:"3"}
        ], CHART_SPECS.fund_usage)''')
        self.assertEqual(got["labels"], ["제9회", "제10회", "제14회"])

    def test_date_x_axis_stays_in_time_order(self):
        """YYYYMMDD·하이픈 ISO 두 형태 모두 시간순이 유지되는지 확인한다
        (숫자 정렬 도입이 날짜 축을 깨뜨리지 않는지)."""
        got = run_js('''chartData([
          {repror:"김", rcept_dt:"2026-12-31", sp_stock_lmp_rate:"2"},
          {repror:"김", rcept_dt:"2026-01-01", sp_stock_lmp_rate:"1"}
        ], CHART_SPECS.insider_timeline)''')
        self.assertEqual(got["labels"], ["2026.01.01", "2026.12.31"])

    def test_categorical_axis_without_any_digits_preserves_original_order(self):
        """리뷰 지적 ⑤: financials의 account_nm처럼 숫자가 전혀 없는
        범주형 값은 가나다순으로 재배열되면 안 된다 — DART 표시 순서
        (원본 등장 순서)를 그대로 지켜야 한다. 여기서는 CHART_SPECS에
        없는 임의의 스펙으로 chartData 자체의 정렬 규칙만 검증한다."""
        got = run_js('''chartData([
          {cat:"유동자산", v:"1"},
          {cat:"자산총계", v:"2"},
          {cat:"부채총계", v:"3"}
        ], {x:"cat", series:[{key:"v", label:"값"}]})''')
        self.assertEqual(got["labels"], ["유동자산", "자산총계", "부채총계"],
                         "숫자가 없는 범주형 축이 원본 순서를 잃었습니다")

    def test_second_record_without_a_value_does_not_blank_the_first(self):
        """리뷰 지적 ③의 정확한 재현: 같은 x(tm)에 레코드가 둘 있고
        뒤엣것에 이 필드 값이 없으면, 앞 레코드의 실값이 null로 덮이면
        안 된다."""
        got = run_js('''chartData([
          {tm:"제1회", plan_amount:"100"},
          {tm:"제1회", real_dtls_amount:"80"}
        ], CHART_SPECS.fund_usage)''')
        by_label = {d["label"]: d["data"] for d in got["datasets"]}
        self.assertEqual(by_label["계획 금액"], [100], "값이 있는 레코드가 값 없는 레코드에 덮였습니다")
        self.assertEqual(by_label["실제 집행 금액"], [80])

    def test_second_record_without_a_value_does_not_blank_the_first_in_group_by_mode(self):
        """같은 재현을 groupBy 계열(insider_timeline, 보고자별)에서도 확인한다
        — series 분기만 고치고 groupBy 분기를 놓치면 이쪽에서 다시 난다.
        고치지 않은 채로는 null이 유일한 값을 지워 차트 자체가 사라진다
        (그릴 값이 하나도 안 남아 chartData가 null을 반환)."""
        got = run_js('''chartData([
          {repror:"김", rcept_dt:"2026-01-01", sp_stock_lmp_rate:"5"},
          {repror:"김", rcept_dt:"2026-01-01", sp_stock_lmp_rate:null}
        ], CHART_SPECS.insider_timeline)''')
        self.assertIsNotNone(got, "실값이 null에 덮여 차트 전체가 사라졌습니다")
        self.assertEqual(got["datasets"][0]["data"], [5])

    def test_same_round_different_report_year_does_not_blank_the_other(self):
        """리뷰 지적 ①의 정확한 재현: fetch_fund_usage(dart_client.py)는
        연도(bsns_year) × 보고서코드 4종을 루프 돌아 **같은 회차가 보고
        시점마다 반복 수집된다**. 실측 사례: 제14회 실제집행이 2024년
        보고에는 50억, 2025년 보고에는 130.8억으로 서로 다르다. 이전에는
        x가 tm 하나뿐이라 뒤 레코드(2025년 보고)가 앞(2024년 보고)을
        조용히 덮어 차트에는 130.8억만 남았다 — 표는 두 행을 그대로
        보여주므로 차트와 표가 다른 값을 말하게 됐다. compositeXFields가
        tm과 year를 함께 x로 묶어 두 보고를 별도 x축 점으로 남긴다."""
        got = run_js('''chartData([
          {tm:"제14회", year:2024, plan_amount:"5000000000", real_dtls_amount:"5000000000"},
          {tm:"제14회", year:2025, plan_amount:"5000000000", real_dtls_amount:"13080000000"}
        ], CHART_SPECS.fund_usage)''')
        self.assertEqual(len(got["labels"]), 2,
                         "같은 회차의 서로 다른 보고연도 값이 하나로 뭉개졌습니다")
        real = next(d for d in got["datasets"] if d["label"] == "실제 집행 금액")
        self.assertEqual(sorted(real["data"]), [5000000000, 13080000000],
                         "값이 있는 레코드가 다른 값이 있는 레코드에 덮였습니다")

    def test_composite_x_falls_back_to_the_single_field_when_the_others_are_absent(self):
        """year 필드가 없는(테스트 픽스처·구 데이터 등) 레코드에서는
        compositeXFields가 tm 하나로 자연히 폴백해야 한다 — 기존
        회차 정렬 동작(test_round_numbers_with_korean_suffix_sort_
        correctly_even_out_of_order 등)을 이 변경이 깨면 안 된다."""
        got = run_js('''chartData([
          {tm:"제10회", plan_amount:"1", real_dtls_amount:"1"},
          {tm:"제9회",  plan_amount:"2", real_dtls_amount:"2"}
        ], CHART_SPECS.fund_usage)''')
        self.assertEqual(got["labels"], ["제9회", "제10회"])

    def test_fund_usage_kind_disambiguates_same_round_and_year(self):
        """라이브 재리뷰 Critical ①의 수정 확인: compositeXFields에 kind가
        빠져 있으면 같은 tm("-")·같은 year라도 공모(public)와 사모(private)
        값이 한 x축 점에서 충돌한다. kind를 더하면 두 값 모두 살아남는다."""
        got = run_js('''chartData([
          {tm:"-", year:2023, kind:"public",  plan_amount:"13082000000", real_dtls_amount:"13082000000"},
          {tm:"-", year:2023, kind:"private", plan_amount:"5000000000",  real_dtls_amount:"5000000000"}
        ], CHART_SPECS.fund_usage)''')
        self.assertEqual(len(got["labels"]), 2,
                         "kind가 다른 두 레코드가 같은 x축 점으로 합쳐졌습니다")
        plan = next(d for d in got["datasets"] if d["label"] == "계획 금액")
        self.assertEqual(sorted(plan["data"]), [5000000000, 13082000000],
                         "kind로 갈라진 두 값이 온전히 보존되지 않았습니다")

    def test_fund_usage_still_conflicting_records_become_null_not_a_guess(self):
        """라이브 재리뷰 Critical ①의 정확한 재현: 공모건의 tm 실측값은
        "-"(회차 없음)이고, 같은 연도·같은 kind(공모) 안에서도 (정규화
        과정에서 탈락하는 reprt_code 탓에) 계획금액이 다른 레코드가 3건
        나온다(실측: 130.82억/352.91억/476.57억). compositeXFields를
        tm+year+kind로 넓혀도 이 세 레코드는 여전히 같은 x축 점에서
        충돌한다 — kind까지 같기 때문이다. 이전에는 뒤 레코드(476.57억)가
        조용히 마지막 값으로 남았지만, 이제는 어느 값이 맞는지 차트가
        판정하지 않고 null이 된다(표는 sectionBlocks가 3행 모두 보여준다,
        아래에서 함께 확인한다)."""
        records_js = '''[
          {tm:"-", year:2023, kind:"public", plan_amount:"13082000000", real_dtls_amount:"13082000000"},
          {tm:"-", year:2023, kind:"public", plan_amount:"35291000000", real_dtls_amount:"35291000000"},
          {tm:"-", year:2023, kind:"public", plan_amount:"47657000000", real_dtls_amount:"47657000000"}
        ]'''
        chart = run_js(f'chartData({records_js}, CHART_SPECS.fund_usage)')
        self.assertIsNone(chart, "값이 서로 다른 3건 중 하나를 차트가 조용히 골라 그렸습니다")

        blocks = run_js(f'sectionBlocks({records_js}, 0, "fund_usage")')
        self.assertEqual(len(blocks[0]["table"]["rows"]), 3,
                         "차트가 사라지면서 표에서도 행이 사라졌습니다 — 표는 그대로 남아야 합니다")

    def test_financials_has_no_chart_spec_to_avoid_mixing_cfs_and_ofs(self):
        """리뷰 지적 ②: financials는 실측에서 fs_div(연결/별도)·sj_div
        (재무상태표/손익계산서)가 상수열이 아니다 — 같은 account_nm이
        연결·별도 양쪽에 나타나 한 그림에 그리면 어느 쪽 값인지 알 수
        없이 뒤섞인다. 나누지 않고 차트 자체를 빼기로 했다(표는 그대로
        fs_div·sj_div 열을 보여준다) — CHART_SPECS에 이 키가 없어야 한다.
        """
        self.assertNotIn("financials", run_js("Object.keys(CHART_SPECS)"))

    def test_returns_null_when_no_records(self):
        for expr in ("chartData([], CHART_SPECS.insider_timeline)",
                     "chartData(null, CHART_SPECS.insider_timeline)"):
            self.assertIsNone(run_js(expr))

    def test_returns_null_when_the_axis_fields_are_absent(self):
        """축 필드가 없으면 차트를 만들지 않는다 — 표는 그대로 남는다."""
        got = run_js('chartData([{무관:1}], CHART_SPECS.insider_timeline)')
        self.assertIsNone(got)

    def test_returns_null_when_every_value_is_missing(self):
        got = run_js('''chartData([{repror:"김", rcept_dt:"2026-01-01",
                        sp_stock_lmp_rate:null}], CHART_SPECS.insider_timeline)''')
        self.assertIsNone(got)

    def test_single_point_series_still_charts(self):
        got = run_js('''chartData([{repror:"김", rcept_dt:"2026-01-01",
                        sp_stock_lmp_rate:"5"}], CHART_SPECS.insider_timeline)''')
        self.assertEqual(got["datasets"][0]["data"], [5])

    # 서버가 주지 않는(STAGE1_SPECS에 없는) 섹션 키인데도 CHART_SPECS에
    # 있는 게 정상인 예외 목록. app.js가 DART 원본이 아니라 **클라이언트가
    # 계산한 파생값**을 렌더하는 섹션이다 — financial_ratios는
    # financialRatios(financials)가 만든 구분·기간·지표·값 레코드를 그린다
    # (financials 자체를 그대로 그리지 않는 이유는 위
    # test_financials_has_no_chart_spec 참고). 서버 레지스트리를 건드리지
    # 않고도(se_server/ API 계약 무변경 원칙) 이 키가 "오타"로 오인돼
    # 이 테스트에 걸리지 않도록 명시적으로 허용한다.
    KNOWN_DERIVED_CHART_KEYS = {"financial_ratios"}

    def test_spec_keys_all_exist_in_the_server_registry(self):
        """CHART_SPECS의 섹션 키는 서버가 실제로 주는 키이거나, 위
        KNOWN_DERIVED_CHART_KEYS에 명시된 클라이언트 파생 섹션이어야 한다.
        어느 쪽도 아니면 오타일 가능성이 높다 — 오타가 있으면 차트가
        조용히 안 그려진다."""
        from se_server.jobs.registry import STAGE1_SPECS

        known = {s.key for s in STAGE1_SPECS} | self.KNOWN_DERIVED_CHART_KEYS
        specs = run_js("Object.keys(CHART_SPECS)")
        unknown = sorted(set(specs) - known)
        self.assertEqual(unknown, [], f"registry에도 없고 파생 섹션 허용목록에도 없는 키: {unknown}")

    def test_no_spec_uses_a_time_scale(self):
        """time 축은 별도 어댑터를 요구한다. category 축만 쓴다.

        리뷰 지적 ⑥: 이전에는 어느 spec에도 xScale 키 자체가 없어
        spec.get("xScale")가 항상 None이었다(무엇을 해도 통과하는 공허한
        검사). 이제 CHART_SPECS 각 항목이 xScale을 실제로 갖고
        renderChart(ui.js)가 이 값을 Chart.js의 scales.x.type으로 쓴다
        (TestChartRenderExecution이 그 배선을 확인한다) — 이 테스트는
        그 값이 "category"이고 "time"이 아님을 직접 확인한다.
        """
        specs = run_js("CHART_SPECS")
        self.assertTrue(specs, "CHART_SPECS가 비어 있어 이 검사가 아무것도 보지 않습니다")
        for key, spec in specs.items():
            self.assertEqual(spec.get("xScale"), "category",
                             f"{key}의 xScale이 'category'가 아닙니다: {spec.get('xScale')!r}")


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestChartDataConflictDetection(unittest.TestCase):
    """chartData의 범용 충돌 감지(writeChartCell) — 같은 (x, 계열)에 서로
    다른 non-null 값이 둘 이상 들어오면 조용히 하나만 남기지 않는다.

    이 부류의 사고가 이 계획에서 세 번(financials·fund_usage·dividends)
    났고, 그때마다 개별 스펙만 고쳤다 — kind·reprt_code처럼 정규화
    과정에서 아예 탈락한 필드가 있으면 키를 아무리 넓혀도 여전히
    충돌할 수 있다. 이 클래스는 특정 섹션이 아니라 chartData 자체의
    방어를 확인한다 — 다음에 같은 부류가 나도 조용히 통과하지 않게
    하는 것이 목적이다(fund_usage·dividends 전용 재현은 각각
    TestChartData·TestChartDataForDividendsDebtDisclosures에 있다)."""

    def test_two_different_values_at_the_same_cell_become_null(self):
        got = run_js('''chartData([
          {cat:"a", v:"1"},
          {cat:"a", v:"2"}
        ], {x:"cat", series:[{key:"v", label:"값"}]})''')
        self.assertIsNone(got, "충돌하는 두 값 중 하나를 차트가 조용히 골라 그렸습니다")

    def test_conflict_at_one_point_does_not_blank_other_points(self):
        """충돌은 그 x축 점 하나만 지운다 — 같은 계열의 다른 점은 살아있다."""
        got = run_js('''chartData([
          {cat:"a", v:"1"},
          {cat:"a", v:"2"},
          {cat:"b", v:"5"}
        ], {x:"cat", series:[{key:"v", label:"값"}]})''')
        self.assertIsNotNone(got, "충돌 없는 다른 점까지 차트 전체가 사라졌습니다")
        self.assertEqual(got["labels"], ["a", "b"])
        self.assertEqual(got["datasets"][0]["data"], [None, 5])

    def test_repeating_the_identical_value_is_not_a_conflict(self):
        """같은 레코드가 우연히 두 번 들어와도(값이 같다) 충돌이 아니다."""
        got = run_js('''chartData([
          {cat:"a", v:"1"},
          {cat:"a", v:"1"}
        ], {x:"cat", series:[{key:"v", label:"값"}]})''')
        self.assertEqual(got["datasets"][0]["data"], [1])

    def test_conflict_persists_even_if_a_later_value_matches_an_earlier_one(self):
        """v1, v2, v1 순서로 와도(세 번째가 첫 값과 우연히 같아도) 충돌
        사실이 사라지고 값이 되살아나면 안 된다 — writeChartCell의
        conflicted 잠금을 확인한다."""
        got = run_js('''chartData([
          {cat:"a", v:"1"},
          {cat:"a", v:"2"},
          {cat:"a", v:"1"}
        ], {x:"cat", series:[{key:"v", label:"값"}]})''')
        self.assertIsNone(got, "충돌 이후 값이 되살아났습니다")

    def test_conflict_detection_also_applies_to_groupby_mode(self):
        """series 분기만 고치고 groupBy 분기(insider_timeline 등, 보고자별
        계열)를 놓치면 이 부류의 사고가 groupBy 쪽에서 다시 난다 — 같은
        보고자·같은 날짜에 서로 다른 지분율이 오는 경우로 재현한다(이전
        (같은 값 없음) 테스트와 달리 이번엔 값 자체가 진짜로 다르다)."""
        got = run_js('''chartData([
          {repror:"김", rcept_dt:"2026-01-01", sp_stock_lmp_rate:"5"},
          {repror:"김", rcept_dt:"2026-01-01", sp_stock_lmp_rate:"7"}
        ], CHART_SPECS.insider_timeline)''')
        self.assertIsNone(got, "같은 보고자·같은 날짜의 서로 다른 지분율이 조용히 하나로 뭉개졌습니다")

    def test_groupby_conflict_does_not_affect_a_different_group(self):
        """충돌이 한 그룹(보고자)에서만 나면 다른 그룹의 데이터는 그대로
        살아있어야 한다 — 그룹 간에 충돌 상태가 새면 안 된다."""
        got = run_js('''chartData([
          {repror:"김", rcept_dt:"2026-01-01", sp_stock_lmp_rate:"5"},
          {repror:"김", rcept_dt:"2026-01-01", sp_stock_lmp_rate:"7"},
          {repror:"이", rcept_dt:"2026-01-01", sp_stock_lmp_rate:"9"}
        ], CHART_SPECS.insider_timeline)''')
        self.assertIsNotNone(got, "다른 보고자의 데이터까지 사라졌습니다")
        by_label = {d["label"]: d["data"] for d in got["datasets"]}
        self.assertEqual(by_label["김"], [None])
        self.assertEqual(by_label["이"], [9])


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestMonthlyCounts(unittest.TestCase):
    """disclosures 월별 집계(monthlyCounts) 순수 함수 검증.

    **집계는 건수를 세는 것에서 끝난다** — 어떤 달이 많았는지 순위를
    매기거나 강조 표시를 만들지 않는다(v0.8.5 판정 금지, task-6-brief.md의
    "막대만 그리고 강조하지 않는다")."""

    def test_counts_records_by_month_prefix(self):
        got = run_js('''monthlyCounts([
          {rcept_dt:"20260415"}, {rcept_dt:"20260420"}, {rcept_dt:"20260501"}
        ], "rcept_dt")''')
        by_month = {r["month"]: r["count"] for r in got}
        self.assertEqual(by_month, {"202604": 2, "202605": 1})

    def test_hyphenated_dates_are_counted_the_same_as_plain_digits(self):
        """insider_timeline의 rcept_dt는 하이픈 있는 실측 형태였다(리뷰
        지적 ④와 같은 부류 함정) — disclosures도 두 형태 모두 같은 달로
        묶여야 한다."""
        got = run_js('''monthlyCounts([
          {rcept_dt:"2026-04-15"}, {rcept_dt:"20260420"}
        ], "rcept_dt")''')
        self.assertEqual(got, [{"month": "202604", "count": 2}])

    def test_missing_or_short_values_are_skipped_not_miscounted(self):
        got = run_js('''monthlyCounts([
          {rcept_dt:null}, {rcept_dt:""}, {rcept_dt:"2026"}, {rcept_dt:"20260415"}
        ], "rcept_dt")''')
        self.assertEqual(got, [{"month": "202604", "count": 1}])

    def test_empty_input_yields_empty_list(self):
        self.assertEqual(run_js('monthlyCounts([], "rcept_dt")'), [])


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestChartDataForDividendsDebtDisclosures(unittest.TestCase):
    """SE-4d Task 6(task-6-brief.md): dividends·debt_balance·disclosures
    차트 데이터 가공. 셋 다 insider_timeline/fund_usage와 형태가 달라
    각각 확인이 필요하다 — dividends는 단위가 섞인 groupBy, debt_balance는
    레코드가 아니라 dict, disclosures는 집계가 필요하다."""

    # ── dividends: se(항목)에 원/%/백만원이 섞여 있다 ──────────────────
    def test_dividends_only_charts_won_denominated_items(self):
        """실측(alotMatter) se 값 예시: "주당액면가액(원)"(원)·
        "현금배당수익률(%)"(%)·"현금배당금총액(백만원)"(백만원)이 한
        목록에 섞여 있다 — "(원)"으로 끝나는 항목만 계열이 되어야 한다."""
        got = run_js('''chartData([
          {se:"주당액면가액(원)", bsns_year:"2024", thstrm:"500"},
          {se:"주당액면가액(원)", bsns_year:"2025", thstrm:"500"},
          {se:"현금배당수익률(%)", bsns_year:"2024", thstrm:"1.2"},
          {se:"현금배당금총액(백만원)", bsns_year:"2024", thstrm:"300"}
        ], CHART_SPECS.dividends)''')
        labels = [d["label"] for d in got["datasets"]]
        self.assertEqual(labels, ["주당액면가액(원)"])

    def test_dividends_excludes_million_won_items_even_though_they_contain_won(self):
        """"(백만원)"에도 문자로는 "원"이 들어 있지만, "(원)"이라는 연속된
        부분 문자열 자체가 없다("(백만원)"의 마지막 네 글자는 "만원)"이지
        "(원)"이 아니다) — 그래서 String.indexOf("(원)")로 판정해도 이
        항목은 이미 걸러진다(-1). 이 테스트는 "(원)"으로 끝나는지
        (endsWith 방식)와 문자열에 "(원)"이 포함되는지(indexOf 방식)를
        가르지 못한다 — 실제로 이 값 하나만으로는 두 방식의 차이가
        드러나지 않는다. 그래도 "숫자만 세는 문자열 포함 검사"(예:
        "원" 한 글자만 찾는 것) 같은 더 느슨한 오탐지를 회귀로부터
        지키는 최소 방어선으로 남겨 둔다."""
        got = run_js('''chartData([
          {se:"현금배당금총액(백만원)", bsns_year:"2024", thstrm:"300"}
        ], CHART_SPECS.dividends)''')
        self.assertIsNone(got, "백만원 단위 항목이 원 단위 차트에 섞여 들어갔습니다")

    def test_dividends_x_axis_is_the_report_year(self):
        got = run_js('''chartData([
          {se:"주당액면가액(원)", bsns_year:"2023", thstrm:"500"},
          {se:"주당액면가액(원)", bsns_year:"2025", thstrm:"500"},
          {se:"주당액면가액(원)", bsns_year:"2024", thstrm:"500"}
        ], CHART_SPECS.dividends)''')
        self.assertEqual(got["labels"], ["2023", "2024", "2025"])

    def test_dividends_returns_null_when_only_percentage_items_exist(self):
        """원 단위 항목이 하나도 없으면(전부 필터에 걸리면) 빈 그림을
        만들지 않고 차트 자체를 만들지 않는다 — 표는 그대로 남는다."""
        got = run_js('''chartData([
          {se:"현금배당수익률(%)", bsns_year:"2024", thstrm:"1.2"},
          {se:"현금배당수익률(%)", bsns_year:"2025", thstrm:"1.5"}
        ], CHART_SPECS.dividends)''')
        self.assertIsNone(got)

    # ── dividends: 라이브 재리뷰 Critical ② — reprt_code·stock_knd가
    #    복합키에 없어 손도 안 댄 채 같은 사고가 났다 ────────────────────
    def test_dividends_reprt_code_key_prevents_quarterly_reports_from_colliding(self):
        """fetch_dividend_history(dart_client.py)는 4개 reprt_code(11011·
        11012·11013·11014) × N년 루프인데, 이전에는 x가 bsns_year 하나뿐
        이었다 — 같은 연도·같은 항목(se)에 보고서마다 다른 값이 조용히
        하나로 덮이고 부호까지 뒤집혔다. 실측(2025년 (연결)주당순이익(원)):
        -3,154 / 1,817 / 2,750 / 121 — 이전에는 마지막 값(121, 흑자)만
        남아 첫 보고(적자)가 사라졌다. reprt_code를 x에 더하면 네 값
        모두 서로 다른 x축 점에 남는다(fund_usage와 달리 reprt_code는
        정규화 과정에서 탈락하지 않는다 — fetch_dividend_history 주석)."""
        got = run_js('''chartData([
          {se:"(연결)주당순이익(원)", bsns_year:"2025", reprt_code:"11011", thstrm:"-3154"},
          {se:"(연결)주당순이익(원)", bsns_year:"2025", reprt_code:"11012", thstrm:"1817"},
          {se:"(연결)주당순이익(원)", bsns_year:"2025", reprt_code:"11013", thstrm:"2750"},
          {se:"(연결)주당순이익(원)", bsns_year:"2025", reprt_code:"11014", thstrm:"121"}
        ], CHART_SPECS.dividends)''')
        self.assertEqual(len(got["labels"]), 4,
                         "같은 연도의 네 분기 보고가 한 x축 점으로 뭉개졌습니다")
        eps = got["datasets"][0]["data"]
        self.assertEqual(sorted(eps), [-3154, 121, 1817, 2750],
                         "부호를 포함한 네 값이 그대로 보존되지 않았습니다 — 적자 보고가 사라졌습니다")

    def test_dividends_reprt_code_key_also_preserves_multi_year_negative_values(self):
        """실측 2024년 (연결)주당순이익(원): -28,306 / -16,885 / -17,387 /
        -19,059 — 전부 적자다. 연도가 다른 레코드와 섞이지 않고, 한 연도
        안의 네 보고 값도 서로 지우지 않고 모두 남아야 한다."""
        got = run_js('''chartData([
          {se:"(연결)주당순이익(원)", bsns_year:"2024", reprt_code:"11011", thstrm:"-28306"},
          {se:"(연결)주당순이익(원)", bsns_year:"2024", reprt_code:"11012", thstrm:"-16885"},
          {se:"(연결)주당순이익(원)", bsns_year:"2024", reprt_code:"11013", thstrm:"-17387"},
          {se:"(연결)주당순이익(원)", bsns_year:"2024", reprt_code:"11014", thstrm:"-19059"}
        ], CHART_SPECS.dividends)''')
        self.assertEqual(len(got["labels"]), 4)
        self.assertEqual(sorted(got["datasets"][0]["data"]), [-28306, -19059, -17387, -16885])

    def test_dividends_stock_knd_key_prevents_common_and_preferred_stock_from_colliding(self):
        """stock_knd(보통주/우선주)가 복합키에 없으면 같은 항목(se)의
        우선주 배당이 보통주 값과 한 계열에서 충돌한다 — compositeGroupFields
        (se+stock_knd)로 계열을 갈라 별도 선으로 만든다."""
        got = run_js('''chartData([
          {se:"주당 현금배당금(원)", stock_knd:"보통주", bsns_year:"2025", reprt_code:"11011", thstrm:"500"},
          {se:"주당 현금배당금(원)", stock_knd:"우선주", bsns_year:"2025", reprt_code:"11011", thstrm:"550"}
        ], CHART_SPECS.dividends)''')
        labels = sorted(d["label"] for d in got["datasets"])
        self.assertEqual(len(labels), 2, "보통주·우선주 배당이 한 계열로 합쳐졌습니다")
        by_label = {d["label"]: d["data"] for d in got["datasets"]}
        self.assertEqual(by_label["주당 현금배당금(원) (보통주)"], [500])
        self.assertEqual(by_label["주당 현금배당금(원) (우선주)"], [550])

    def test_dividends_group_filter_suffix_still_applies_when_group_is_composite(self):
        """계열 이름이 compositeGroupFields로 "항목 (주식종류)" 형태가 돼도,
        "(원)" 필터는 원래 필드(se)를 보고 판정해야 한다 — 계열 이름 자체
        ("...(원) (보통주)")는 "(원)"으로 끝나지 않으므로, 필터가 합성된
        이름을 잘못 보면 원 단위 항목까지 전부 걸러진다."""
        got = run_js('''chartData([
          {se:"주당 현금배당금(원)", stock_knd:"보통주", bsns_year:"2025", reprt_code:"11011", thstrm:"500"},
          {se:"현금배당수익률(%)", stock_knd:"보통주", bsns_year:"2025", reprt_code:"11011", thstrm:"1.2"}
        ], CHART_SPECS.dividends)''')
        self.assertIsNotNone(got, "필터가 합성 이름을 보고 원 단위 항목까지 전부 걸러냈습니다")
        labels = [d["label"] for d in got["datasets"]]
        self.assertEqual(labels, ["주당 현금배당금(원) (보통주)"])

    def test_dividends_table_still_shows_all_four_quarterly_rows(self):
        """검증 요구: 차트가 네 점으로 갈라지는 동안 표(sectionBlocks)도
        네 행 그대로 남아야 한다 — 차트만 고치고 표를 죽이면 안 된다."""
        records_js = '''[
          {se:"(연결)주당순이익(원)", bsns_year:"2025", reprt_code:"11011", thstrm:"-3154"},
          {se:"(연결)주당순이익(원)", bsns_year:"2025", reprt_code:"11012", thstrm:"1817"},
          {se:"(연결)주당순이익(원)", bsns_year:"2025", reprt_code:"11013", thstrm:"2750"},
          {se:"(연결)주당순이익(원)", bsns_year:"2025", reprt_code:"11014", thstrm:"121"}
        ]'''
        blocks = run_js(f'sectionBlocks({records_js}, 0, "dividends")')
        self.assertEqual(len(blocks[0]["table"]["rows"]), 4)

    # ── debt_balance: 레코드 리스트가 아니라 dict다 ────────────────────
    def test_debt_balance_charts_normalized_records(self):
        got = run_js('''chartData(
          normalizeDebtByKind({corporate_bond:{total:1000,maturity_under_1y:200},
                               short_term_bond:{total:500,maturity_under_1y:500}}),
          CHART_SPECS.debt_balance
        )''')
        self.assertEqual(got["labels"], ["회사채", "단기사채"])
        self.assertEqual(
            [d["label"] for d in got["datasets"]], ["합계", "1년 이내 만기 금액"]
        )
        totals = next(d for d in got["datasets"] if d["label"] == "합계")
        self.assertEqual(totals["data"], [1000, 500])

    def test_debt_balance_returns_null_for_the_raw_by_kind_dict(self):
        """정규화(normalizeDebtByKind) 없이 by_kind dict를 그대로 넘기면
        (records가 배열이 아니다) chartData는 그리지 않는다 — 별도 처리가
        빠지면 조용히 안 그려진다는 것 자체를 확인한다."""
        got = run_js('''chartData(
          {corporate_bond:{total:1000,maturity_under_1y:200}},
          CHART_SPECS.debt_balance
        )''')
        self.assertIsNone(got)

    # ── disclosures: 월별 집계는 chartData 안에서만 끝난다 ──────────────
    def test_disclosures_charts_monthly_counts(self):
        got = run_js('''chartData([
          {rcept_no:1, rcept_dt:"20260415", report_nm:"a"},
          {rcept_no:2, rcept_dt:"20260420", report_nm:"b"},
          {rcept_no:3, rcept_dt:"20260501", report_nm:"c"}
        ], CHART_SPECS.disclosures)''')
        self.assertEqual(got["labels"], ["2026.04", "2026.05"])
        self.assertEqual(got["datasets"], [{"label": "건수", "data": [2, 1]}])

    def test_disclosures_returns_null_when_no_valid_dates(self):
        got = run_js('chartData([{rcept_no:1, report_nm:"a"}], CHART_SPECS.disclosures)')
        self.assertIsNone(got)

    def test_disclosures_table_records_stay_individual_not_aggregated(self):
        """집계는 가공이다(브리프) — chartData 내부에서만 일어나야 하고,
        sectionBlocks가 만드는 표(및 그 records)는 원본 건수 그대로
        남아야 한다. 145건이 2개 월로 뭉개지면 안 된다."""
        got = run_js('''sectionBlocks([
          {rcept_no:1, rcept_dt:"20260415", report_nm:"a"},
          {rcept_no:2, rcept_dt:"20260420", report_nm:"b"},
          {rcept_no:3, rcept_dt:"20260501", report_nm:"c"}
        ], 0, "disclosures")''')
        self.assertEqual(len(got), 1)
        self.assertEqual(len(got[0]["table"]["rows"]), 3, "표가 월별로 집계되어 버렸습니다")
        self.assertEqual(len(got[0]["records"]), 3)


# ── SE-4f Task 3: 공시 목록 차트 유형별 색상 분류 ────────────────────────
#
# task-3-brief.md: "로직을 새로 만들지 마라 — docs/tool/index.html의
# matchSignals(564행)·AMEND_RE가 이미 있다. 읽어서 맞춘다." 공개 뷰어와
# SE가 같은 공시를 다르게 분류하면 그 자체가 결함이므로, 아래 테스트는
# 고정 픽스처가 아니라 **실제** docs/tool/signals-data.json을 읽어
# 검증한다(그 파일이 나중에 바뀌어도 이 계약이 계속 맞는지 자동으로
# 지킨다).
_SIGNALS_DATA_PATH = _ROOT / "docs" / "tool" / "signals-data.json"


def run_js_with_real_signals(expression: str):
    """app.js를 불러오고, 공개 뷰어와 공유하는 실제 signals-data.json을
    전역 SIGNALS로 얹어 표현식을 평가한다."""
    script = (
        f"Object.assign(globalThis, require({json.dumps(str(_APP))}));\n"
        f"globalThis.SIGNALS = JSON.parse("
        f"require('fs').readFileSync({json.dumps(str(_SIGNALS_DATA_PATH))}, 'utf-8'));\n"
        f"process.stdout.write(JSON.stringify({expression}));\n"
    )
    out = subprocess.run(
        [_NODE, "-e", script], capture_output=True, text=True, encoding="utf-8"
    )
    if out.returncode != 0:
        raise AssertionError(f"node 실행 실패:\n{out.stderr}")
    return json.loads(out.stdout)


def call_js(fn_name: str, *json_args) -> object:
    """fn_name(json_args...)를 JSON 리터럴로 안전하게 호출한다 — 손으로
    JS 문자열 이스케이프를 쓰지 않아 따옴표·역슬래시 실수를 피한다."""
    args_src = ", ".join(json.dumps(a, ensure_ascii=False) for a in json_args)
    return run_js(f"{fn_name}({args_src})")


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestClassifyDisclosureCategory(unittest.TestCase):
    """classifyDisclosureCategory(reportNm, signalsData) — 공시 하나를
    signals-data.json 기준으로 카테고리 번호(0~8, 0="기타")로 분류한다.
    docs/tool/index.html의 matchSignals+AMEND_RE와 같은 로직이어야 한다.

    픽스처는 브리프가 요구한 엔켐 실제 공시명이다."""

    def test_matches_a_known_keyword_to_its_signals_data_category(self):
        got = run_js_with_real_signals(
            'classifyDisclosureCategory("주요사항보고서(전환사채권발행결정)", SIGNALS)'
        )
        self.assertEqual(got, 1, "CB_BW(category 1)로 분류돼야 합니다")

    def test_unclassified_report_falls_back_to_other_category_zero(self):
        """브리프 실측 예시 — 어떤 신호 키워드에도 걸리지 않는 공시다.
        분류되지 않는다고 사라지면 안 되고 "기타"(0)로 남아야 한다."""
        got = run_js_with_real_signals(
            'classifyDisclosureCategory("타법인주식및출자증권취득결정", SIGNALS)'
        )
        self.assertEqual(got, 0)

    def test_second_unclassified_example_also_falls_back(self):
        got = run_js_with_real_signals(
            'classifyDisclosureCategory("주요사항보고서(타법인주식및출자증권양도결정)", SIGNALS)'
        )
        self.assertEqual(got, 0)

    def test_amendment_disclosure_is_not_classified_like_the_public_viewer(self):
        """docs/tool/index.html의 buildResult: isAmend면 신호를 아예
        매기지 않는다(sigs=[]) — "[기재정정]"이 안에 "전환사채"를
        포함해도 공개 뷰어와 똑같이 기타(0)로 남아야 한다. 되돌리면(정정
        판정을 빼면) 이 테스트는 1(CB_REPAY 또는 CB_BW)로 실패한다."""
        got = run_js_with_real_signals(
            'classifyDisclosureCategory('
            '"[기재정정]주요사항보고서(자기전환사채매도결정)", SIGNALS)'
        )
        self.assertEqual(got, 0)

    def test_matches_public_viewer_logic_for_a_batch_of_real_report_names(self):
        """docs/tool/index.html의 matchSignals+AMEND_RE를 파이썬으로 그대로
        재현해, classifyDisclosureCategory의 결과가 공개 뷰어가 매길 첫
        신호의 category와 일치하는지 배치로 대조한다 — "로직을 새로
        만들지 마라"를 기계적으로 강제한다."""
        data = json.loads(_SIGNALS_DATA_PATH.read_text(encoding="utf-8"))
        amend_re = re.compile(data["amendment_pattern"])
        samples = [
            "[기재정정]주요사항보고서(자기전환사채매도결정)",
            "타법인주식및출자증권취득결정",
            "주요사항보고서(타법인주식및출자증권양도결정)",
            "주요사항보고서(전환사채권발행결정)",
            "최대주주변경",
            "임원의변동",
            "조회공시요구(풍문또는보도에대한답변)",
            "제3자배정유상증자결정",
        ]

        def public_viewer_category(nm: str) -> int:
            if amend_re.match(nm):
                return 0
            for s in data["signals"]:
                for kw in s["keywords"]:
                    if kw and kw in nm:
                        return s["category"]
            return 0

        expected = [public_viewer_category(nm) for nm in samples]
        got = run_js_with_real_signals(
            json.dumps(samples, ensure_ascii=False)
            + ".map(function(nm){return classifyDisclosureCategory(nm, SIGNALS);})"
        )
        self.assertEqual(got, expected)

    def test_returns_null_when_signals_data_is_unusable(self):
        """로드 실패(브리프: "로드 실패에 대비하세요")에 대응하는 계약 —
        null이거나 형태가 예상과 다르면 분류를 포기했다는 신호로 null을
        돌려준다. 호출자(monthlyCountsByCategory/chartData)가 이 신호로
        기존 단색 집계로 물러난다."""
        self.assertIsNone(run_js('classifyDisclosureCategory("x", null)'))
        self.assertIsNone(run_js('classifyDisclosureCategory("x", {})'))
        self.assertIsNone(
            run_js('classifyDisclosureCategory("x", {signals: "not-array"})')
        )


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestMonthlyCountsByCategory(unittest.TestCase):
    """monthlyCountsByCategory(rows, dateField, textField, signalsData) —
    disclosures를 월×카테고리로 묶어 건수만 센다(monthlyCounts와 같은
    "집계는 여기서 끝난다" 원칙, v0.8.5)."""

    _SMALL_SIGNALS = {
        "signals": [
            {"key": "CB_BW", "category": 1, "keywords": ["전환사채권발행결정"]},
            {"key": "SHAREHOLDER", "category": 3, "keywords": ["최대주주변경"]},
        ],
        "categories": {"0": "기타", "1": "CB/채권", "3": "경영권"},
        "amendment_pattern": r"^\[(?:기재정정|첨부추가|정정)[^\]]*\]\s*",
    }

    def test_splits_counts_by_month_and_category(self):
        records = [
            {"rcept_dt": "20260110", "report_nm": "주요사항보고서(전환사채권발행결정)"},
            {"rcept_dt": "20260112", "report_nm": "최대주주변경"},
            {"rcept_dt": "20260115", "report_nm": "타법인주식및출자증권취득결정"},
            {"rcept_dt": "20260210", "report_nm": "[기재정정]주요사항보고서(자기전환사채매도결정)"},
        ]
        got = call_js(
            "monthlyCountsByCategory", records, "rcept_dt", "report_nm", self._SMALL_SIGNALS
        )
        by_month: dict = {}
        for r in got:
            by_month.setdefault(r["month"], {})[r["category"]] = r["count"]
        self.assertEqual(by_month["202601"], {"CB/채권": 1, "경영권": 1, "기타": 1})
        self.assertEqual(by_month["202602"], {"기타": 1})

    def test_month_totals_match_the_original_record_count(self):
        """브리프의 핵심 요구: "월별 합계가 원본 건수와 일치해야 합니다."
        미분류·정정공시를 포함해 어떤 공시도 조용히 빠지면 안 된다."""
        records = [
            {"rcept_dt": "20260110", "report_nm": "a"},
            {"rcept_dt": "20260112", "report_nm": "b"},
            {"rcept_dt": "20260115", "report_nm": "c"},
            {"rcept_dt": "20260210", "report_nm": "d"},
        ]
        got = call_js(
            "monthlyCountsByCategory", records, "rcept_dt", "report_nm", self._SMALL_SIGNALS
        )
        self.assertEqual(sum(r["count"] for r in got), len(records))

    def test_missing_or_short_dates_are_skipped_not_miscounted(self):
        """monthlyCounts와 같은 계약 — 월을 특정할 수 없는 값은 0으로
        채우지 않고 건너뛴다."""
        records = [
            {"rcept_dt": None, "report_nm": "a"},
            {"rcept_dt": "2026", "report_nm": "b"},
            {"rcept_dt": "20260415", "report_nm": "최대주주변경"},
        ]
        got = call_js(
            "monthlyCountsByCategory", records, "rcept_dt", "report_nm", self._SMALL_SIGNALS
        )
        self.assertEqual(got, [{"month": "202604", "category": "경영권", "count": 1}])


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestChartDataDisclosuresByType(unittest.TestCase):
    """chartData(records, CHART_SPECS.disclosures, signalsData) — 공시
    목록 월별 막대를 유형별로 쌓아 올리는 계약. 3번째 인자를 생략하거나
    (기존 호출부) 못 쓸 형태면 기존 단색 막대로 물러난다(브리프: "로드
    실패에 대비하세요"). signalsData는 순수 함수의 인자일 뿐이라(브리프:
    "순수 함수는 분류 데이터를 인자로 받아 순수하게 유지") chartData
    자체는 여전히 같은 입력에 같은 출력을 낸다."""

    _RECORDS = [
        {"rcept_no": 1, "rcept_dt": "20260110", "report_nm": "주요사항보고서(전환사채권발행결정)"},
        {"rcept_no": 2, "rcept_dt": "20260112", "report_nm": "최대주주변경"},
        {"rcept_no": 3, "rcept_dt": "20260115", "report_nm": "타법인주식및출자증권취득결정"},
        {"rcept_no": 4, "rcept_dt": "20260210", "report_nm": "[기재정정]주요사항보고서(자기전환사채매도결정)"},
        {"rcept_no": 5, "rcept_dt": "20260212", "report_nm": "주요사항보고서(타법인주식및출자증권양도결정)"},
    ]

    def test_without_signals_data_falls_back_to_a_single_solid_series(self):
        """기존 호출부(2-인자)와 완전히 같은 동작을 유지해야 한다 — 이
        저장소에서 결함이 초록으로 통과한 전례가 있어(브리프) 회귀
        방지로 명시적으로 남긴다."""
        got = run_js(
            f"chartData({json.dumps(self._RECORDS, ensure_ascii=False)}, "
            f"CHART_SPECS.disclosures)"
        )
        self.assertEqual([d["label"] for d in got["datasets"]], ["건수"])
        self.assertEqual(sum(got["datasets"][0]["data"]), len(self._RECORDS))

    def test_malformed_signals_data_also_falls_back_gracefully(self):
        """null뿐 아니라 형태가 깨진 값(예: signals 배열이 없음)에도
        화면이 죽지 않고 기존 단색 막대로 물러나야 한다."""
        got = run_js(
            f"chartData({json.dumps(self._RECORDS, ensure_ascii=False)}, "
            f"CHART_SPECS.disclosures, {{}})"
        )
        self.assertEqual([d["label"] for d in got["datasets"]], ["건수"])

    def test_with_real_signals_data_splits_into_type_stacked_series(self):
        got = run_js_with_real_signals(
            f"chartData({json.dumps(self._RECORDS, ensure_ascii=False)}, "
            f"CHART_SPECS.disclosures, SIGNALS)"
        )
        self.assertIsNotNone(got)
        labels = [d["label"] for d in got["datasets"]]
        self.assertIn("기타", labels, "미분류 공시가 조용히 사라졌습니다")
        self.assertGreater(len(labels), 1, "유형이 하나로만 나와 색 구분의 의미가 없습니다")

    def test_monthly_stacked_sum_matches_the_original_disclosure_count_per_month(self):
        """브리프의 핵심 요구: "월별 합계가 원본 건수와 일치해야 합니다."
        엔켐 145건이면 145여야 한다는 요구를 축소판(5건, 2개월)으로
        검증한다."""
        got = run_js_with_real_signals(
            f"chartData({json.dumps(self._RECORDS, ensure_ascii=False)}, "
            f"CHART_SPECS.disclosures, SIGNALS)"
        )
        per_month_total = [0] * len(got["labels"])
        for ds in got["datasets"]:
            for i, v in enumerate(ds["data"]):
                if v is not None:
                    per_month_total[i] += v
        self.assertEqual(got["labels"], ["2026.01", "2026.02"])
        self.assertEqual(per_month_total, [3, 2])
        self.assertEqual(sum(per_month_total), len(self._RECORDS))

    def test_amendment_disclosure_is_counted_under_other_not_dropped(self):
        """브리프 실측 예시 — 정정공시가 조용히 사라지지 않고 "기타"
        막대에 포함돼야 한다."""
        got = run_js_with_real_signals(
            f"chartData({json.dumps(self._RECORDS, ensure_ascii=False)}, "
            f"CHART_SPECS.disclosures, SIGNALS)"
        )
        other_ds = next(d for d in got["datasets"] if d["label"] == "기타")
        feb_idx = got["labels"].index("2026.02")
        self.assertIsNotNone(other_ds["data"][feb_idx])
        self.assertGreaterEqual(other_ds["data"][feb_idx], 1)

    def test_chart_spec_declares_stacking(self):
        """renderChart(ui.js)가 Chart.js scales.x/y.stacked로 그대로 옮길
        플래그다 — spec에 없으면 렌더 경로가 읽을 값 자체가 없다."""
        self.assertTrue(run_js("!!CHART_SPECS.disclosures.stacked"))


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestNumeric(unittest.TestCase):
    """numeric()의 쉼표·배열 처리(리뷰 지적 ⑦ minor).

    이전에는 쉼표를 무조건 지우고("1,2,3" → "123") 배열을 String()으로
    문자열화해(String([5]) === "5") 우연히 숫자로 읽었다 — 둘 다 없는
    숫자를 만들어내는 쪽의 실수다(0으로 채우는 것과 같은 부류의 거짓말).
    """

    def test_thousands_grouped_comma_is_parsed(self):
        """정상적인 3자리 그룹 쉼표는 그대로 지원해야 한다(회귀 방지)."""
        self.assertEqual(run_js('numeric("13,082,000,000")'), 13082000000)

    def test_malformed_comma_grouping_is_not_silently_concatenated(self):
        """"1,2,3"은 자릿수가 3자리씩 묶이지 않은 잘못된 형태다 — 쉼표를
        그냥 지우면 없는 숫자 123이 만들어진다."""
        self.assertIsNone(run_js('numeric("1,2,3")'))

    def test_array_is_not_coerced_into_a_number(self):
        """String([5]) === "5"라 배열이 우연히 숫자처럼 읽히던 사고."""
        self.assertIsNone(run_js("numeric([5])"))

    def test_array_of_multiple_items_is_not_coerced_either(self):
        self.assertIsNone(run_js("numeric([1,2])"))

    def test_plain_number_and_numeric_string_still_work(self):
        self.assertEqual(run_js("numeric(5)"), 5)
        self.assertEqual(run_js('numeric("5.5")'), 5.5)

    def test_non_numeric_string_is_null(self):
        self.assertIsNone(run_js('numeric("-")'))

    def test_empty_string_is_null_not_zero(self):
        """M2: numeric("")이 0을 돌려주면 "그 시점 값이 0이었다"는 거짓말이
        된다(이 화면의 헤드라인 원칙, numeric() 자체의 주석과 동일) — 지금
        까지는 이 경계를 직접 확인하는 테스트가 없어 `return 0`으로 바꿔도
        초록이었다."""
        self.assertIsNone(run_js('numeric("")'))
        self.assertIsNone(run_js('numeric("   ")'))


# ── renderChart 실제 렌더 경로 재현용 가짜 DOM ──────────────────────────
#
# 위 TestChartData는 chartData()(app.js 순수 함수)만 검증한다 — renderChart
# (ui.js, DOM을 직접 만진다)는 실제로 canvas를 만들고 Chart를 생성자로
# 부르고 destroy()하는지까지는 못 잡는다. "정의만 있고 호출부가 없다"가
# 이 저장소에서 다섯 번 났다는 브리프 경고에 따라, Chart 생성자를 스텁으로
# 주입해 실제로 어떤 데이터로 불렸는지 기록한다.
#
# document.createDocumentFragment로 만든 조각을 appendChild하면(tableEl이
# 그렇게 만든다) 진짜 브라우저는 조각의 자식을 부모로 옮기고 조각 자체는
# 사라진다(네이티브 DocumentFragment 동작) — 이 가짜 FakeEl도 그 동작을
# 흉내 내야 renderChart의 `wrap.querySelector("table")`가 실제 브라우저와
# 같은 자리에서 <table>을 찾는다(안 그러면 표가 fragment 껍데기 안에
# 갇혀 canvas를 표 바로 위로 끼워 넣지 못한다).
_CHART_RENDER_HARNESS = r"""
const vm = require("vm");
const fs = require("fs");

const ELEMENTS = Object.create(null);
const DESTROYED = [];
const UPDATED = [];
const CHART_CALLS = [];

class FakeClassList {
  constructor() { this._set = new Set(); }
  add(c) { this._set.add(c); }
  remove(c) { this._set.delete(c); }
  contains(c) { return this._set.has(c); }
}

class FakeEl {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this._text = "";
    this._className = "";
    this._id = "";
    this.dataset = {};
    this._listeners = {};
    this._attrs = {};
    this.hidden = false;
    this.classList = new FakeClassList();
  }
  appendChild(c) {
    // 네이티브 DocumentFragment 동작 재현 — 조각을 그대로 자식으로 넣지
    // 않고, 조각의 자식을 이 노드로 옮긴다(위 하네스 설명 참고).
    if (c && c.tag === "#fragment") {
      while (c.children.length) this.children.push(c.children.shift());
      return c;
    }
    this.children.push(c);
    return c;
  }
  insertBefore(node, ref) {
    const idx = ref ? this.children.indexOf(ref) : -1;
    if (idx === -1) this.children.push(node);
    else this.children.splice(idx, 0, node);
    return node;
  }
  removeChild(c) {
    const idx = this.children.indexOf(c);
    if (idx !== -1) this.children.splice(idx, 1);
    return c;
  }
  get firstChild() { return this.children.length ? this.children[0] : null; }
  insertRow() { const tr = new FakeEl("tr"); this.appendChild(tr); return tr; }
  insertCell() { const td = new FakeEl("td"); this.appendChild(td); return td; }
  createTHead() { const el = new FakeEl("thead"); this.appendChild(el); return el; }
  createTBody() { const el = new FakeEl("tbody"); this.appendChild(el); return el; }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  dispatch(type) { (this._listeners[type] || []).forEach(function (fn) { fn({}); }); }
  setAttribute(k, v) { this._attrs[k] = String(v); }
  getAttribute(k) {
    return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null;
  }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text; }
  set className(v) { this._className = v; }
  get className() { return this._className; }
  set id(v) { this._id = v; ELEMENTS[v] = this; }
  get id() { return this._id; }
  // renderChart가 쓰는 선택자("table")만 최소 지원한다 — 모든 자손을
  // 재귀로 훑는다(네이티브 querySelector와 같은 범위).
  querySelector(sel) {
    if (sel !== "table") return null;
    const stack = this.children.slice();
    while (stack.length) {
      const n = stack.shift();
      if (!n) continue;
      if (n.tag === "table") return n;
      if (n.children && n.children.length) stack.push.apply(stack, n.children);
    }
    return null;
  }
}

function makeEl(tag, id) {
  const el = new FakeEl(tag);
  if (id) el.id = id;
  return el;
}

const bodyEl = makeEl("div", "body");
makeEl("nav", "toc");
makeEl("div", "company-info");
makeEl("section", "gate");
makeEl("main", "main");
makeEl("p", "gate-msg");
makeEl("aside", "panel");
makeEl("div", "panel-body");
makeEl("span", "head-name");
makeEl("div", "bar");
makeEl("button", "actor-btn");

const documentElement = new FakeEl("html");

// 테마별로 다른 값을 주는 CSS 변수 스텁 — index.html의 실제 값 자체를
// 검증하지 않는다(그건 정적 검사 쪽 몫이다). 여기서는 "테마가 바뀌면
// 차트에 적용된 색도 실제로 바뀐다"만 확인하면 된다.
const CSS_VARS = {
  dark: { "--dim2": "#9fb0c0", "--tx": "#d7dde6",
          "--c0": "#5b8ff9", "--c1": "#61ddaa", "--c2": "#f6bd16" },
  light: { "--dim2": "#333c48", "--tx": "#1c222b",
           "--c0": "#2f5fd0", "--c1": "#1f9d6e", "--c2": "#ad8c00" },
};

function fakeGetComputedStyle(el) {
  const theme = el.getAttribute("data-theme") === "light" ? "light" : "dark";
  const vars = CSS_VARS[theme];
  return { getPropertyValue: function (name) { return vars[name] || ""; } };
}

class FakeChart {
  constructor(canvas, config) {
    this.canvas = canvas;
    this.config = config;
    this.options = config.options;
    this.data = config.data;
    CHART_CALLS.push(this);
  }
  update() { UPDATED.push(this); }
  destroy() { DESTROYED.push(this); }
}

function collectTags(node, out) {
  out = out || [];
  if (!node) return out;
  out.push({ tag: node.tag, className: node.className || "" });
  (node.children || []).forEach(function (c) { collectTags(c, out); });
  return out;
}

// 리뷰 검증 요구(①): 차트가 만든 값과 표가 만든 값을 실제 렌더 결과에서
// 직접 대조하려면 표 <table>의 셀 텍스트를 읽어야 한다 — collectTags는
// tag·className만 모으므로 이 목적에는 쓸 수 없다.
function findTable(node) {
  if (!node) return null;
  if (node.tag === "table") return node;
  for (const c of (node.children || [])) {
    const found = findTable(c);
    if (found) return found;
  }
  return null;
}
function tableRowTexts(tableNode) {
  const tbody = (tableNode.children || []).find(function (c) { return c.tag === "tbody"; });
  if (!tbody) return [];
  return tbody.children
    .filter(function (tr) { return tr.className !== "fold-detail"; })
    .map(function (tr) {
      return tr.children
        .filter(function (td) { return td.tag === "td"; })
        .map(function (td) { return td.textContent; });
    });
}

const sandbox = {
  console: console,
  Chart: FakeChart,
  getComputedStyle: fakeGetComputedStyle,
  document: {
    documentElement: documentElement,
    createElement: function (tag) { return new FakeEl(tag); },
    createDocumentFragment: function () { return new FakeEl("#fragment"); },
    createTextNode: function (t) { const n = new FakeEl("#text"); n.textContent = t; return n; },
    addEventListener: function () {},
    getElementById: function (id) { return ELEMENTS[id] || null; },
  },
  localStorage: {
    getItem: function () { return null; },
    setItem: function () {},
    removeItem: function () {},
  },
  fetch: function () { return Promise.reject(new Error("no network in test")); },
};
vm.createContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[1], "utf-8"), { filename: "app.js" }).runInContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[2], "utf-8"), { filename: "ui.js" }).runInContext(sandbox);

sandbox.openDocPanel = function () {};

// A) fund_usage — CHART_SPECS에 series(계획 vs 실제) 정의가 있다. tm은
//    실측(field-inventory) 형태인 "제N회"를 쓰고(브리프의 가짜 형태
//    "1"·"2"였던 것을 되돌린다 — 리뷰 지적 ②), 사전식으로 이미 뒤섞인
//    순서("제10회"가 "제9회"보다 먼저)로 넣어 axisSortKey(회차 정렬)가
//    되돌아가도 이 렌더 테스트가 실제로 잡아내는지 확인한다.
sandbox.renderSection("fund_usage", [
  { tm: "제10회", plan_amount: "500000000", real_dtls_amount: "500000000" },
  { tm: "제9회", plan_amount: "1300000000", real_dtls_amount: "800000000" },
]);
const fundTags = collectTags(bodyEl, []);
const fundChart = CHART_CALLS[0];

// B) insider_timeline — source별로 쪼개진 블록마다 자기 레코드만 받는지
//    확인한다. elestock 그룹만 CHART_SPECS가 요구하는 필드(rcept_dt·
//    sp_stock_lmp_rate)를 갖고 있고, hyslr 그룹은 없다 — elestock 블록만
//    차트가 생겨야 한다. rcept_dt는 실측(field-inventory) 형태인 하이픈
//    ISO("2026-03-04")를 쓴다(브리프의 가짜 형태 "20260304"였던 것을
//    되돌린다 — 리뷰 지적 ②) — axisLabel의 하이픈 분기가 되돌아가도 이
//    렌더 테스트가 실제로 잡아내는지 확인한다.
sandbox.renderSection("insider_timeline", [
  { source: "elestock", repror: "오정강", rcept_dt: "2026-03-04", sp_stock_lmp_rate: "14.13" },
  { source: "elestock", repror: "오정강", rcept_dt: "2026-03-27", sp_stock_lmp_rate: "3.60" },
  { source: "hyslr", mxmm_shrholdr_nm: "홍길동", posesn_stock_co: "1000" },
]);
const chartCountAfterB = CHART_CALLS.length;
const insiderChart = CHART_CALLS[1];

// C) shareholders — CHART_SPECS에 정의가 아예 없다. 차트가 늘면 안 된다.
sandbox.renderSection("shareholders", { major_holders: [{ nm: "a" }] });
const chartCountAfterC = CHART_CALLS.length;

// D) showGate — 지금까지 만든 인스턴스가 전부 destroy()되는지 확인한다.
sandbox.showGate("메시지");
const destroyedAfterGate = DESTROYED.length;

// E) 재렌더 후 테마 전환 — repaintCharts가 살아있는 인스턴스의 색을
//    실제로 바꾸고 update()를 부르는지 확인한다.
sandbox.renderSection("fund_usage", [
  { tm: "1", plan_amount: "100", real_dtls_amount: "80" },
]);
const themedChart = CHART_CALLS[CHART_CALLS.length - 1];
const colorBeforeTheme = themedChart.options.scales.x.ticks.color;
sandbox.applyTheme("light");
const colorAfterTheme = themedChart.options.scales.x.ticks.color;
const updatedAfterTheme = UPDATED.indexOf(themedChart) !== -1;

// F) dividends — se(항목)에 원/%가 섞여 있다. "(원)"으로 끝나는 항목만
//    계열이 되어야 한다(판정선: 단위가 다른 값을 한 그림에 섞지 않는다).
//    차트가 실제로 생겼는지는 개수 스냅샷으로 확인한다 — 안 생기면
//    CHART_CALLS의 마지막 원소는 이전(E) 차트를 가리키는 낡은 참조가
//    되어 조용히 통과하는 함정이 있다(카운트 비교로 그 함정을 막는다).
const chartCountBeforeF = CHART_CALLS.length;
sandbox.renderSection("dividends", [
  { se: "주당액면가액(원)", bsns_year: "2024", thstrm: "500" },
  { se: "주당액면가액(원)", bsns_year: "2025", thstrm: "500" },
  { se: "현금배당수익률(%)", bsns_year: "2024", thstrm: "1.2" },
  { se: "현금배당수익률(%)", bsns_year: "2025", thstrm: "1.5" },
]);
const chartCountAfterF = CHART_CALLS.length;
const dividendsChart = chartCountAfterF > chartCountBeforeF ? CHART_CALLS[CHART_CALLS.length - 1] : null;

// G) debt_balance — by_kind는 dict라, sectionBlocks의 특수 정규화
//    (normalizeDebtByKind) 없이는 chartData가 그릴 x축(debt_kind)이
//    레코드에 없다.
const chartCountBeforeG = CHART_CALLS.length;
sandbox.renderSection("debt_balance", {
  year: "2025", total: 1500,
  by_kind: {
    corporate_bond: { total: 1000, maturity_under_1y: 200 },
    short_term_bond: { total: 500, maturity_under_1y: 500 },
  },
  equity_ratio: null, maturity_1y_share: 46.7,
});
const chartCountAfterG = CHART_CALLS.length;
const debtChart = chartCountAfterG > chartCountBeforeG ? CHART_CALLS[CHART_CALLS.length - 1] : null;

// H) disclosures — 개별 건이 아니라 월별 건수만 그려야 한다(집계는
//    chartData 내부 파생값, 표는 별도 순수 함수 테스트가 원본 그대로임을
//    확인한다).
const chartCountBeforeH = CHART_CALLS.length;
sandbox.renderSection("disclosures", [
  { rcept_no: 1, rcept_dt: "20260415", report_nm: "a" },
  { rcept_no: 2, rcept_dt: "20260420", report_nm: "b" },
  { rcept_no: 3, rcept_dt: "20260501", report_nm: "c" },
]);
const chartCountAfterH = CHART_CALLS.length;
const disclosuresChart = chartCountAfterH > chartCountBeforeH ? CHART_CALLS[CHART_CALLS.length - 1] : null;

// I) 같은 섹션을 다시 그리면 이전 Chart 인스턴스가 정리돼야 한다(리뷰
//    지적 ④) — holder.removeChild만으로는 DOM에서 canvas가 빠질 뿐,
//    Chart.js 인스턴스는 CHART_INSTANCES에 남아 다음 사용자 화면까지
//    쌓인다. showGate()의 resetCharts()가 아니라 renderSection 자체가
//    정리해야 하는 경로다(같은 회사 안에서 같은 섹션이 다시 오는 경우).
const destroyedBeforeSectionRerender = DESTROYED.length;
sandbox.renderSection("fund_usage", [
  { tm: "제20회", plan_amount: "1000000000", real_dtls_amount: "500000000" },
]);
const chartsAfterFirstRerender = CHART_CALLS.length;
sandbox.renderSection("fund_usage", [
  { tm: "제21회", plan_amount: "2000000000", real_dtls_amount: "1000000000" },
]);
const chartsAfterSecondRerender = CHART_CALLS.length;
const destroyedAfterSectionRerender = DESTROYED.length;

// K) 리뷰 지적 ①의 종단 검증: 같은 회차(tm="제14회")가 서로 다른 연도
//    (year) 보고에서 다른 실제 집행 금액으로 나타난 리뷰의 재현 사례를
//    그대로 쓴다(2024년 보고 50억, 2025년 보고 130.8억). compositeXFields가
//    없으면 뒤 레코드가 앞을 조용히 덮어 차트에는 130.8억만 남고 표는
//    그대로 두 행을 보여줘 차트와 표가 다른 값을 말하게 된다 — 여기서는
//    순수 함수(chartData)가 아니라 renderSection 전체 경로로 차트가 실제로
//    만든 값과 표(<table>)가 실제로 그린 값을 직접 대조한다. plan_amount는
//    두 보고에서 값이 같다(계획은 안 바뀐다) — tm과 함께 캡션으로 승격돼
//    본문 열에서 빠지므로, 남는 본문 열은 [year, real_dtls_amount] 둘뿐이다.
sandbox.renderSection("fund_usage", [
  { tm: "제14회", year: 2024, plan_amount: "5000000000", real_dtls_amount: "5000000000" },
  { tm: "제14회", year: 2025, plan_amount: "5000000000", real_dtls_amount: "13080000000" },
]);
const sameRoundChart = CHART_CALLS[CHART_CALLS.length - 1];
const sameRoundTable = findTable(ELEMENTS["sec-fund_usage"]);
const sameRoundTableRows = sameRoundTable ? tableRowTexts(sameRoundTable) : [];

// L) disclosures — SIGNALS_DATA(신호 분류 데이터, SE-4f Task 3)가 있으면
//    renderSection이 실제로 그 값을 renderChart까지 배선해 월별 막대가
//    유형별로 쌓여야 한다. 정의만 있고 호출부가 없는 사고가 이 저장소에서
//    다섯 번 났다(TestPanelsAreWiredAndReachable 등) — 문자열 검사가
//    아니라 실제 렌더 결과로 확인한다.
//
//    SIGNALS_DATA는 ui.js 최상위 `let` 선언이라 sandbox 객체 프로퍼티로는
//    안 보인다(vm 렉시컬 환경 특성 — 함수 선언과 달리 let/const는 전역
//    객체에 반영되지 않는다). 같은 컨텍스트에서 대입문만 담은 별도
//    vm.Script를 돌려 그 바인딩 자체를 바꾼다.
new vm.Script(
  "SIGNALS_DATA = " + JSON.stringify({
    signals: [
      { key: "CB_BW", label: "CB/BW발행", keywords: ["전환사채권발행결정"], category: 1 },
      { key: "SHAREHOLDER", label: "최대주주변경", keywords: ["최대주주변경"], category: 3 },
    ],
    categories: { "0": "기타", "1": "CB/채권", "3": "경영권" },
    amendment_pattern: "^\\[(?:기재정정|첨부추가|정정)[^\\]]*\\]\\s*",
  }) + ";",
  { filename: "inject-signals-data.js" }
).runInContext(sandbox);

const chartCountBeforeL = CHART_CALLS.length;
sandbox.renderSection("disclosures", [
  { rcept_no: 10, rcept_dt: "20260110", report_nm: "주요사항보고서(전환사채권발행결정)" },
  { rcept_no: 11, rcept_dt: "20260112", report_nm: "최대주주변경" },
  { rcept_no: 12, rcept_dt: "20260115", report_nm: "타법인주식및출자증권취득결정" },
  { rcept_no: 13, rcept_dt: "20260210", report_nm: "[기재정정]주요사항보고서(자기전환사채매도결정)" },
]);
const chartCountAfterL = CHART_CALLS.length;
const byTypeChart = chartCountAfterL > chartCountBeforeL ? CHART_CALLS[CHART_CALLS.length - 1] : null;

function findIndex(tags, tag) {
  for (let i = 0; i < tags.length; i++) if (tags[i].tag === tag) return i;
  return -1;
}
const canvasIdx = findIndex(fundTags, "canvas");
const tableIdx = findIndex(fundTags, "table");

process.stdout.write(JSON.stringify({
  fundLabels: fundChart.data.labels,
  fundDatasets: fundChart.data.datasets.map(function (d) {
    return { label: d.label, data: d.data, color: d.borderColor };
  }),
  fundTooltip0: fundChart.config.options.plugins.tooltip.callbacks.label(
    { datasetIndex: 0, dataset: { label: "계획 금액" }, parsed: { y: 1300000000 } }),
  fundTooltip1: fundChart.config.options.plugins.tooltip.callbacks.label(
    { datasetIndex: 1, dataset: { label: "실제 집행 금액" }, parsed: { y: 800000000 } }),
  // L1: spanGaps가 실제로 Chart.js 데이터셋 옵션까지 전달되는지(true로
  // 바뀌어도 지금까지는 어느 테스트도 못 잡았다) 확인하기 위한 원본 값.
  fundDatasetSpanGaps: fundChart.data.datasets.map(function (d) { return d.spanGaps; }),
  canvasIdx: canvasIdx,
  tableIdx: tableIdx,
  fundXScaleType: fundChart.options.scales.x.type,
  fundHasTableCells: fundTags.some(function (t) { return t.tag === "td"; }),
  canvasClassName: canvasIdx === -1 ? null : fundTags[canvasIdx].className,
  canvasRole: fundChart.canvas.getAttribute("role"),
  canvasAriaLabel: fundChart.canvas.getAttribute("aria-label"),
  chartCountAfterA: 1,
  chartCountAfterB: chartCountAfterB,
  chartCountAfterC: chartCountAfterC,
  insiderLabels: insiderChart.data.labels,
  insiderDatasetLabels: insiderChart.data.datasets.map(function (d) { return d.label; }),
  destroyedAfterGate: destroyedAfterGate,
  colorBeforeTheme: colorBeforeTheme,
  colorAfterTheme: colorAfterTheme,
  updatedAfterTheme: updatedAfterTheme,
  chartCountBeforeF: chartCountBeforeF,
  chartCountAfterF: chartCountAfterF,
  dividendsLabels: dividendsChart ? dividendsChart.data.labels : null,
  dividendsDatasetLabels: dividendsChart
    ? dividendsChart.data.datasets.map(function (d) { return d.label; }) : null,
  chartCountBeforeG: chartCountBeforeG,
  chartCountAfterG: chartCountAfterG,
  debtLabels: debtChart ? debtChart.data.labels : null,
  debtDatasetLabels: debtChart
    ? debtChart.data.datasets.map(function (d) { return d.label; }) : null,
  debtTotals: debtChart ? debtChart.data.datasets[0].data : null,
  chartCountBeforeH: chartCountBeforeH,
  chartCountAfterH: chartCountAfterH,
  disclosuresLabels: disclosuresChart ? disclosuresChart.data.labels : null,
  disclosuresData: disclosuresChart ? disclosuresChart.data.datasets[0].data : null,
  destroyedBeforeSectionRerender: destroyedBeforeSectionRerender,
  chartsAfterFirstRerender: chartsAfterFirstRerender,
  chartsAfterSecondRerender: chartsAfterSecondRerender,
  destroyedAfterSectionRerender: destroyedAfterSectionRerender,
  sameRoundChartLabels: sameRoundChart.data.labels,
  sameRoundChartRealData: sameRoundChart.data.datasets.find(function (d) {
    return d.label === "실제 집행 금액";
  }).data,
  sameRoundTableRows: sameRoundTableRows,
  chartCountBeforeL: chartCountBeforeL,
  chartCountAfterL: chartCountAfterL,
  byTypeLabels: byTypeChart ? byTypeChart.data.labels : null,
  byTypeDatasetLabels: byTypeChart
    ? byTypeChart.data.datasets.map(function (d) { return d.label; }) : null,
  byTypeDatasetData: byTypeChart
    ? byTypeChart.data.datasets.map(function (d) { return d.data; }) : null,
  byTypeColors: byTypeChart
    ? byTypeChart.data.datasets.map(function (d) { return d.backgroundColor; }) : null,
  byTypeXStacked: byTypeChart ? byTypeChart.options.scales.x.stacked : null,
  byTypeYStacked: byTypeChart ? byTypeChart.options.scales.y.stacked : null,
}));
"""


def run_chart_render():
    out = subprocess.run(
        [_NODE, "-e", _CHART_RENDER_HARNESS, str(_APP), str(_UI)],
        capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode != 0:
        raise AssertionError(f"node 실행 실패:\n{out.stderr}")
    return json.loads(out.stdout)


# ── 회사 전환(renderHeadPlaceholder) 차트 정리 경로 재현용 가짜 DOM ──────
#
# M1: showGate()의 resetCharts() 호출(로그아웃·세션 만료)은 위
# TestChartRenderExecution.test_show_gate_destroys_every_tracked_chart_
# instance가 이미 확인한다. 하지만 같은 세션에서 회사만 바꿔 다시
# 분석하는 경로(renderHeadPlaceholder, doAnalyze가 새 조회를 시작할 때
# 호출)에는 지금까지 테스트가 없었다 — 그 resetCharts() 호출을 지워도
# 전부 초록이었다. _CHART_RENDER_HARNESS(위)는 이미 매우 길고 여러
# 블록이 CHART_CALLS 개수에 서로 의존하므로, 그 안에 끼워 넣으면
# renderHeadPlaceholder가 SEC_WRAP·ELEMENTS를 건드리는 부작용이 뒤 블록의
# 가정(예: 같은 섹션의 "재렌더")을 깨뜨릴 위험이 있다 — 별도의 작고
# 독립된 시나리오로 분리한다(FakeEl·FakeChart는 위 하네스와 같은 최소
# 구현을 그대로 쓴다).
_COMPANY_SWITCH_HARNESS = r"""
const vm = require("vm");
const fs = require("fs");

const ELEMENTS = Object.create(null);
const DESTROYED = [];
const CHART_CALLS = [];

class FakeClassList {
  constructor() { this._set = new Set(); }
  add(c) { this._set.add(c); }
  remove(c) { this._set.delete(c); }
  contains(c) { return this._set.has(c); }
}

class FakeEl {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this._text = "";
    this._className = "";
    this._id = "";
    this.dataset = {};
    this._listeners = {};
    this._attrs = {};
    this.hidden = false;
    this.classList = new FakeClassList();
  }
  appendChild(c) {
    if (c && c.tag === "#fragment") {
      while (c.children.length) this.children.push(c.children.shift());
      return c;
    }
    this.children.push(c);
    return c;
  }
  insertBefore(node, ref) {
    const idx = ref ? this.children.indexOf(ref) : -1;
    if (idx === -1) this.children.push(node);
    else this.children.splice(idx, 0, node);
    return node;
  }
  removeChild(c) {
    const idx = this.children.indexOf(c);
    if (idx !== -1) this.children.splice(idx, 1);
    return c;
  }
  insertRow() { const tr = new FakeEl("tr"); this.appendChild(tr); return tr; }
  insertCell() { const td = new FakeEl("td"); this.appendChild(td); return td; }
  createTHead() { const el = new FakeEl("thead"); this.appendChild(el); return el; }
  createTBody() { const el = new FakeEl("tbody"); this.appendChild(el); return el; }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  dispatch(type) { (this._listeners[type] || []).forEach(function (fn) { fn({}); }); }
  setAttribute(k, v) { this._attrs[k] = String(v); }
  getAttribute(k) {
    return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null;
  }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text; }
  set className(v) { this._className = v; }
  get className() { return this._className; }
  set id(v) { this._id = v; ELEMENTS[v] = this; }
  get id() { return this._id; }
  querySelector(sel) {
    if (sel !== "table") return null;
    const stack = this.children.slice();
    while (stack.length) {
      const n = stack.shift();
      if (!n) continue;
      if (n.tag === "table") return n;
      if (n.children && n.children.length) stack.push.apply(stack, n.children);
    }
    return null;
  }
}

function makeEl(tag, id) {
  const el = new FakeEl(tag);
  if (id) el.id = id;
  return el;
}

const bodyEl = makeEl("div", "body");
makeEl("nav", "toc");
makeEl("div", "company-info");
makeEl("section", "gate");
makeEl("main", "main");
makeEl("p", "gate-msg");
makeEl("aside", "panel");
makeEl("div", "panel-body");
makeEl("span", "head-name");
makeEl("div", "bar");
makeEl("button", "actor-btn");

const documentElement = new FakeEl("html");

function fakeGetComputedStyle() {
  return { getPropertyValue: function () { return "#000"; } };
}

class FakeChart {
  constructor(canvas, config) {
    this.canvas = canvas;
    this.config = config;
    this.options = config.options;
    this.data = config.data;
    CHART_CALLS.push(this);
  }
  update() {}
  destroy() { DESTROYED.push(this); }
}

const sandbox = {
  console: console,
  Chart: FakeChart,
  getComputedStyle: fakeGetComputedStyle,
  document: {
    documentElement: documentElement,
    createElement: function (tag) { return new FakeEl(tag); },
    createDocumentFragment: function () { return new FakeEl("#fragment"); },
    createTextNode: function (t) { const n = new FakeEl("#text"); n.textContent = t; return n; },
    addEventListener: function () {},
    getElementById: function (id) { return ELEMENTS[id] || null; },
  },
  localStorage: {
    getItem: function () { return null; },
    setItem: function () {},
    removeItem: function () {},
  },
  fetch: function () { return Promise.reject(new Error("no network in test")); },
};
vm.createContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[1], "utf-8"), { filename: "app.js" }).runInContext(sandbox);
new vm.Script(fs.readFileSync(process.argv[2], "utf-8"), { filename: "ui.js" }).runInContext(sandbox);

sandbox.openDocPanel = function () {};

// 1) A사 조회 — 차트가 하나 생긴다.
sandbox.renderSection("fund_usage", [
  { tm: "1", plan_amount: "100", real_dtls_amount: "80" },
]);
const chartsBeforeSwitch = CHART_CALLS.length;
const destroyedBeforeSwitch = DESTROYED.length;

// 2) 회사 전환 — doAnalyze()가 새 조회를 시작할 때 부르는 경로
//    (renderHeadPlaceholder)를 그대로 재현한다. 이 호출이 resetCharts()를
//    부르지 않으면 A사 차트 인스턴스가 그대로 남는다.
sandbox.renderHeadPlaceholder("B사");
const chartsAfterSwitch = CHART_CALLS.length;
const destroyedAfterSwitch = DESTROYED.length;

// 3) 전환 후 B사 조회 — resetToc()가 SEC_WRAP을 비웠다면 같은 키
//    ("fund_usage")라도 처음 그리는 것처럼 새 차트가 생겨야 한다.
sandbox.renderSection("fund_usage", [
  { tm: "1", plan_amount: "200", real_dtls_amount: "150" },
]);
const chartsAfterPostSwitchRender = CHART_CALLS.length;

process.stdout.write(JSON.stringify({
  chartsBeforeSwitch: chartsBeforeSwitch,
  destroyedBeforeSwitch: destroyedBeforeSwitch,
  chartsAfterSwitch: chartsAfterSwitch,
  destroyedAfterSwitch: destroyedAfterSwitch,
  chartsAfterPostSwitchRender: chartsAfterPostSwitchRender,
}));
"""


def run_company_switch():
    out = subprocess.run(
        [_NODE, "-e", _COMPANY_SWITCH_HARNESS, str(_APP), str(_UI)],
        capture_output=True, text=True, encoding="utf-8",
    )
    if out.returncode != 0:
        raise AssertionError(f"node 실행 실패:\n{out.stderr}")
    return json.loads(out.stdout)


@unittest.skipUnless(_NODE, "node가 없어 ui.js의 실제 차트 렌더 경로를 검증할 수 없습니다")
class TestChartRenderExecution(unittest.TestCase):
    """renderChart(ui.js)를 Chart 생성자 스텁으로 실제 실행해, 정의만 있고
    호출부가 죽어 있는 사고(이 저장소에서 다섯 번 났다)를 문자열 검사가
    아니라 실제 렌더 결과로 확인한다."""

    def test_chart_is_created_with_labels_and_series_datasets(self):
        """입력 순서는 "제10회"가 "제9회"보다 먼저다(리뷰 지적 ②의 실측
        형태 픽스처) — axisSortKey(회차 정렬)가 실제로 동작해야 출력이
        회차 순(9→10)으로 나온다."""
        got = run_chart_render()
        self.assertEqual(got["fundLabels"], ["제9회", "제10회"])
        self.assertEqual(
            [d["label"] for d in got["fundDatasets"]],
            ["계획 금액", "실제 집행 금액"],
        )
        self.assertEqual(got["fundDatasets"][0]["data"], [1300000000, 500000000])
        self.assertEqual(got["fundDatasets"][1]["data"], [800000000, 500000000])

    def test_x_scale_type_comes_from_the_spec_not_hardcoded(self):
        """리뷰 지적 ⑥: CHART_SPECS.fund_usage.xScale("category")이 실제로
        Chart.js 옵션(scales.x.type)까지 전달되는지 확인한다 — spec에
        키만 있고 렌더 경로가 안 읽으면 죽은 설정이 된다."""
        got = run_chart_render()
        self.assertEqual(got["fundXScaleType"], "category")

    def test_tooltip_uses_format_value_so_it_matches_the_table(self):
        """억/조 표기가 표와 어긋나면 같은 값을 두 가지로 말하는 셈이 된다."""
        got = run_chart_render()
        self.assertEqual(got["fundTooltip0"], "계획 금액: 13억")
        self.assertEqual(got["fundTooltip1"], "실제 집행 금액: 8억")

    def test_span_gaps_is_false_so_missing_points_are_not_bridged(self):
        """L1: renderChart(ui.js)가 데이터셋마다 spanGaps: false를 명시한다
        (Chart.js 기본값을 명시적으로 고정 — 값이 없는 구간을 이어붙이면
        추세선처럼 보여 판정이 된다, v0.8.5). 지금까지는 이 값을 확인하는
        테스트가 없어 true로 바꿔도 초록이었다."""
        got = run_chart_render()
        self.assertTrue(got["fundDatasetSpanGaps"], "spanGaps 값 자체가 비었습니다")
        for v in got["fundDatasetSpanGaps"]:
            self.assertIs(v, False, "spanGaps가 false가 아닙니다 — 값 없는 구간이 이어질 수 있습니다")

    def test_series_colors_differ_and_avoid_the_verdict_red(self):
        got = run_chart_render()
        c0 = got["fundDatasets"][0]["color"]
        c1 = got["fundDatasets"][1]["color"]
        self.assertNotEqual(c0, c1, "계열 색이 구분되지 않습니다")
        for c in (c0, c1):
            self.assertNotIn(c, ("#e0564a", "#b3261e"),
                             "차트 계열 색이 판정 색(--red)과 같습니다")

    def test_canvas_is_inserted_above_the_table_which_still_renders(self):
        got = run_chart_render()
        self.assertNotEqual(got["canvasIdx"], -1, "canvas가 만들어지지 않았습니다")
        self.assertNotEqual(got["tableIdx"], -1, "표가 사라졌습니다")
        self.assertLess(got["canvasIdx"], got["tableIdx"],
                        "차트가 표 위가 아니라 아래(또는 표 대신)에 있습니다")
        self.assertTrue(got["fundHasTableCells"], "표 셀 데이터가 사라졌습니다")
        self.assertEqual(got["canvasClassName"], "chart-canvas")

    def test_source_split_block_only_charts_the_group_with_axis_fields(self):
        """insider_timeline은 source별로 쪼개진다 — CHART_SPECS가 요구하는
        필드(rcept_dt·sp_stock_lmp_rate)를 가진 elestock 블록만 차트가
        생기고, 필드가 없는 hyslr 블록은 표만 남아야 한다."""
        got = run_chart_render()
        self.assertEqual(got["chartCountAfterB"] - got["chartCountAfterA"], 1,
                         "source로 쪼개진 블록마다 각각 그려지지 않았거나, "
                         "필드가 없는 블록에서도 차트가 생겼습니다")
        self.assertEqual(got["insiderLabels"], ["2026.03.04", "2026.03.27"])
        self.assertEqual(got["insiderDatasetLabels"], ["오정강"])

    def test_no_chart_spec_means_no_new_chart(self):
        got = run_chart_render()
        self.assertEqual(got["chartCountAfterC"], got["chartCountAfterB"],
                         "CHART_SPECS에 없는 섹션인데 차트가 생겼습니다")

    def test_show_gate_destroys_every_tracked_chart_instance(self):
        got = run_chart_render()
        self.assertEqual(got["destroyedAfterGate"], got["chartCountAfterC"],
                         "showGate()가 그 시점까지 만든 차트를 전부 destroy()하지 않습니다")

    def test_theme_toggle_actually_repaints_an_existing_chart(self):
        got = run_chart_render()
        self.assertNotEqual(got["colorBeforeTheme"], got["colorAfterTheme"],
                            "테마를 바꿔도 이미 그려진 차트의 축 색이 그대로입니다")
        self.assertTrue(got["updatedAfterTheme"],
                        "테마를 바꿔도 차트의 update()가 불리지 않습니다")

    def test_dividends_chart_only_includes_won_denominated_series(self):
        """SE-4d Task 6: renderSection("dividends", ...)이 실제로 차트를
        만들고, "(원)"으로 끝나지 않는 항목(퍼센트)은 계열에서 빠지는지
        실제 렌더 경로로 확인한다."""
        got = run_chart_render()
        self.assertEqual(got["chartCountAfterF"] - got["chartCountBeforeF"], 1,
                         "dividends 차트가 실제 렌더 경로에서 생기지 않았습니다")
        self.assertEqual(got["dividendsLabels"], ["2024", "2025"])
        self.assertEqual(got["dividendsDatasetLabels"], ["주당액면가액(원)"],
                         "퍼센트 항목이 원 단위 차트에 섞여 들어갔습니다")

    def test_debt_balance_chart_reads_the_normalized_by_kind_records(self):
        """debt_balance.by_kind는 dict라 sectionBlocks의 특수 처리
        (normalizeDebtByKind)가 배선돼야만 차트가 나온다 — 실제 렌더
        경로로 확인한다."""
        got = run_chart_render()
        self.assertEqual(got["chartCountAfterG"] - got["chartCountBeforeG"], 1,
                         "debt_balance 차트가 실제 렌더 경로에서 생기지 않았습니다")
        self.assertEqual(got["debtLabels"], ["회사채", "단기사채"])
        self.assertEqual(got["debtDatasetLabels"], ["합계", "1년 이내 만기 금액"])
        self.assertEqual(got["debtTotals"], [1000, 500])

    def test_disclosures_chart_shows_monthly_counts_not_raw_rows(self):
        """실제 렌더 경로로 disclosures 차트가 개별 3건이 아니라 월별
        집계(2개월)로 그려지는지 확인한다."""
        got = run_chart_render()
        self.assertEqual(got["chartCountAfterH"] - got["chartCountBeforeH"], 1,
                         "disclosures 차트가 실제 렌더 경로에서 생기지 않았습니다")
        self.assertEqual(got["disclosuresLabels"], ["2026.04", "2026.05"])
        self.assertEqual(got["disclosuresData"], [2, 1])

    def test_disclosures_chart_splits_into_type_stacked_series_when_signals_data_is_set(self):
        """SE-4f Task 3: SIGNALS_DATA가 채워져 있으면 renderSection이 실제로
        그 값을 renderChart까지 배선해, 월별 막대가 (CB/채권·경영권·기타)
        유형별로 갈라져야 한다 — 정의만 있고 호출부가 없는 사고(이 저장소
        다섯 번째)를 실제 렌더 결과로 잡는다."""
        got = run_chart_render()
        self.assertEqual(got["chartCountAfterL"] - got["chartCountBeforeL"], 1,
                         "disclosures 유형별 차트가 실제 렌더 경로에서 생기지 않았습니다")
        self.assertEqual(got["byTypeLabels"], ["2026.01", "2026.02"])
        labels = got["byTypeDatasetLabels"]
        self.assertIn("기타", labels, "미분류/정정 공시가 조용히 사라졌습니다")
        self.assertGreater(len(labels), 1, "유형이 하나로만 나와 색 구분의 의미가 없습니다")
        # 월별 합계가 원본 건수(1월 3건, 2월 1건)와 일치해야 한다(브리프).
        totals = [0, 0]
        for data in got["byTypeDatasetData"]:
            for i, v in enumerate(data):
                if v is not None:
                    totals[i] += v
        self.assertEqual(totals, [3, 1])

    def test_disclosures_chart_uses_stacked_scales_and_distinct_non_verdict_colors(self):
        got = run_chart_render()
        self.assertTrue(got["byTypeXStacked"], "x축이 stacked로 설정되지 않았습니다")
        self.assertTrue(got["byTypeYStacked"], "y축이 stacked로 설정되지 않았습니다")
        colors = got["byTypeColors"]
        self.assertEqual(len(colors), len(set(colors)), "유형별 계열 색이 구분되지 않습니다")
        for c in colors:
            self.assertNotIn(c, ("#e0564a", "#b3261e"),
                             "차트 계열 색이 판정 색(--red)과 같습니다")

    def test_canvas_has_an_accessible_role_and_label(self):
        """리뷰 지적 ⑤: canvas 안의 그림은 스크린 리더가 읽지 못한다 —
        role="img" + aria-label로 최소한 무슨 차트인지는 전달해야 한다."""
        got = run_chart_render()
        self.assertEqual(got["canvasRole"], "img")
        self.assertTrue(got["canvasAriaLabel"], "canvas에 aria-label이 없습니다")

    def test_rerendering_a_section_destroys_the_previous_chart_instance(self):
        """리뷰 지적 ④: renderSection이 holder만 비우고 그 안의 Chart
        인스턴스는 CHART_INSTANCES에 남으면, 회사를 바꾸지 않고 같은
        섹션이 다시 그려질 때마다(showGate()가 부르는 resetCharts()를
        거치지 않는 경로) 캔버스와 리스너가 계속 쌓인다."""
        got = run_chart_render()
        self.assertEqual(got["chartsAfterSecondRerender"] - got["chartsAfterFirstRerender"], 1,
                         "같은 섹션을 다시 그렸는데 새 Chart 인스턴스가 생기지 않았습니다")
        self.assertGreater(got["destroyedAfterSectionRerender"], got["destroyedBeforeSectionRerender"],
                           "섹션을 다시 그려도 이전 Chart 인스턴스가 destroy()되지 않습니다")

    def test_same_fund_round_different_report_year_agrees_between_chart_and_table(self):
        """검증 요구(①): 리뷰가 재현한 실제 사례 — 제14회가 2024년 보고에는
        50억, 2025년 보고에는 130.8억으로 다르게 잡힌다. 순수 함수
        (chartData) 단위 테스트가 아니라 renderSection 전체 경로로, 차트가
        실제로 그린 값과 표(<table>)가 실제로 그린 값을 직접 대조한다 —
        compositeXFields 없이 x가 tm 하나뿐이면 뒤 레코드(130.8억)가
        앞(50억)을 조용히 덮어 차트에는 하나만 남고, 표는 그대로 두 행을
        보여줘 차트와 표가 다른 값을 말하게 된다."""
        got = run_chart_render()
        self.assertEqual(len(got["sameRoundChartLabels"]), 2,
                         "같은 회차의 서로 다른 보고연도가 차트에서 하나로 뭉개졌습니다")
        chart_values = set(got["sameRoundChartRealData"])
        self.assertEqual(chart_values, {5000000000, 13080000000},
                         "차트의 실제 집행 금액 두 값이 리뷰가 재현한 사례와 다릅니다")

        self.assertEqual(len(got["sameRoundTableRows"]), 2, "표가 두 행을 보여주지 않습니다")
        # 본문 열은 [year, real_dtls_amount] 순서다 — tm·plan_amount는 두
        # 보고에서 값이 같아 caption으로 승격돼 본문에서 빠진다(위 하네스
        # 블록 K 주석 참고). 마지막 열이 실제 집행 금액이다.
        table_amounts = set(row[-1] for row in got["sameRoundTableRows"])
        self.assertEqual(table_amounts, {"50억", "130.8억"},
                         "표의 실제 집행 금액 두 값이 리뷰가 재현한 사례와 다릅니다")


@unittest.skipUnless(_NODE, "node가 없어 ui.js의 실제 회사 전환 경로를 검증할 수 없습니다")
class TestCompanySwitchDestroysCharts(unittest.TestCase):
    """M1: 회사 전환(renderHeadPlaceholder) 경로에서도 이전 회사의 Chart
    인스턴스가 destroy()되는지 확인한다. showGate()의 resetCharts()
    호출은 이미 다른 테스트(test_show_gate_destroys_every_tracked_chart_
    instance)가 지키지만, 로그아웃을 거치지 않고 같은 세션에서 회사만
    바꾸는 이 경로는 지금까지 아무 테스트도 지키지 않았다 — resetCharts()
    호출을 지워도 전부 초록이었다."""

    def test_switching_company_destroys_the_previous_charts(self):
        got = run_company_switch()
        self.assertEqual(got["chartsBeforeSwitch"], 1)
        self.assertGreater(got["destroyedAfterSwitch"], got["destroyedBeforeSwitch"],
                           "회사를 전환해도 이전 회사의 Chart 인스턴스가 destroy()되지 않습니다")
        self.assertEqual(got["destroyedAfterSwitch"], got["chartsBeforeSwitch"],
                         "회사 전환 시점까지 만든 차트 전부가 destroy()되지 않았습니다")

    def test_switching_company_alone_does_not_create_a_new_chart(self):
        """전환 자체는 정리만 한다 — 아직 아무 섹션도 다시 그리지 않았으니
        새 차트가 생기면 안 된다."""
        got = run_company_switch()
        self.assertEqual(got["chartsAfterSwitch"], got["chartsBeforeSwitch"])

    def test_rendering_the_same_section_key_after_switch_creates_a_fresh_chart(self):
        """전환 후 같은 섹션 키("fund_usage")로 B사를 그려도, SEC_WRAP이
        비워져 있어야(resetToc()) "처음 그리는 것"으로 취급돼 새 차트가
        생긴다 — 그러지 않으면 A사의 표·차트 잔재 위에 B사 값이 잘못
        이어붙을 수 있다."""
        got = run_company_switch()
        self.assertEqual(got["chartsAfterPostSwitchRender"], got["chartsAfterSwitch"] + 1)


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestFinancialRatios(unittest.TestCase):
    # 엔켐 2025 사업보고서 연결 실측값(계정과목 전체 — API 직접 조회).
    # 당기순이익은 DART 원문 그대로 "당기순이익(손실)"로 온다(괄호 포함) —
    # 브리프 픽스처에 이 계정이 아예 없어서 별칭 결함이 초록으로 통과했던
    # 사고를 재현 방지하려고 실측 전체 계정을 그대로 옮겨 적는다.
    # "법인세차감전 순이익"도 함께 넣어 별칭이 그 계정을 "당기순이익"으로
    # 잘못 집지 않는지 같은 픽스처로 검증한다.
    _CFS = """[
      {fs_div:"CFS", sj_div:"BS", account_nm:"유동자산",
       thstrm_amount:"355,778,989,218", frmtrm_amount:"442,931,976,422"},
      {fs_div:"CFS", sj_div:"BS", account_nm:"비유동자산",
       thstrm_amount:"751,770,189,243"},
      {fs_div:"CFS", sj_div:"BS", account_nm:"자산총계",
       thstrm_amount:"1,107,549,178,461"},
      {fs_div:"CFS", sj_div:"BS", account_nm:"유동부채",
       thstrm_amount:"580,445,377,198", frmtrm_amount:"618,068,574,810"},
      {fs_div:"CFS", sj_div:"BS", account_nm:"비유동부채",
       thstrm_amount:"46,078,749,534"},
      {fs_div:"CFS", sj_div:"BS", account_nm:"부채총계",
       thstrm_amount:"626,524,126,732", frmtrm_amount:"675,004,911,778"},
      {fs_div:"CFS", sj_div:"BS", account_nm:"자본금",
       thstrm_amount:"10,925,068,000", frmtrm_amount:"10,555,112,500"},
      {fs_div:"CFS", sj_div:"BS", account_nm:"이익잉여금",
       thstrm_amount:"-677,559,097,436"},
      {fs_div:"CFS", sj_div:"BS", account_nm:"자본총계",
       thstrm_amount:"481,025,051,729", frmtrm_amount:"484,842,224,968"},
      {fs_div:"CFS", sj_div:"IS", account_nm:"매출액",
       thstrm_amount:"312,794,042,228", frmtrm_amount:"365,708,579,550"},
      {fs_div:"CFS", sj_div:"IS", account_nm:"영업이익",
       thstrm_amount:"-78,386,657,935", frmtrm_amount:"-50,403,019,697"},
      {fs_div:"CFS", sj_div:"IS", account_nm:"법인세차감전 순이익",
       thstrm_amount:"-58,836,298,293"},
      {fs_div:"CFS", sj_div:"IS", account_nm:"당기순이익(손실)",
       thstrm_amount:"-70,567,058,674", frmtrm_amount:"-558,294,328,262"},
      {fs_div:"CFS", sj_div:"IS", account_nm:"총포괄손익",
       thstrm_amount:"-71,645,284,911"}
    ]"""

    def test_operating_margin_matches_hand_calculation(self):
        got = run_js(f"financialRatios({self._CFS})")
        cur = [r for r in got if r["지표"] == "영업이익률" and r["기간"] == "당기"][0]
        self.assertAlmostEqual(cur["값"], -25.1, places=1)

    def test_debt_ratio_matches_hand_calculation(self):
        got = run_js(f"financialRatios({self._CFS})")
        cur = [r for r in got if r["지표"] == "부채비율" and r["기간"] == "당기"][0]
        self.assertAlmostEqual(cur["값"], 130.2, places=1)

    def test_net_margin_resolves_the_parenthesized_account_name(self):
        """DART가 실제로 주는 계정명은 "당기순이익(손실)"이다(괄호 포함,
        엔켐 실측) — 정확 일치만 보면 이 지표가 영원히 null이 된다."""
        got = run_js(f"financialRatios({self._CFS})")
        cur = [r for r in got if r["지표"] == "순이익률" and r["기간"] == "당기"][0]
        self.assertAlmostEqual(cur["값"], -22.6, places=1)
        pri = [r for r in got if r["지표"] == "순이익률" and r["기간"] == "전기"][0]
        self.assertAlmostEqual(pri["값"], -152.7, places=1)

    def test_current_ratio_matches_hand_calculation(self):
        got = run_js(f"financialRatios({self._CFS})")
        cur = [r for r in got if r["지표"] == "유동비율" and r["기간"] == "당기"][0]
        self.assertAlmostEqual(cur["값"], 61.3, places=1)

    def test_alias_does_not_pick_pretax_income_as_net_income(self):
        """"법인세차감전 순이익"도 "순이익"을 포함하지만 당기순이익이 아니다.
        별칭이 이 계정을 대신 집으면 값은 나오지만 틀린 숫자다 — 값이
        없는 것보다 나쁘다(브리프 경고)."""
        got = run_js('''financialRatios([
          {fs_div:"CFS", sj_div:"IS", account_nm:"매출액", thstrm_amount:"1000"},
          {fs_div:"CFS", sj_div:"IS", account_nm:"법인세차감전 순이익", thstrm_amount:"999"}
        ])''')
        r = [x for x in got if x["지표"] == "순이익률"][0]
        self.assertIsNone(r["값"])
        self.assertIn("당기순이익", r.get("사유", ""))

    def test_prior_period_is_computed_too(self):
        """한 시점만 계산하면 추이가 안 나온다 — 그게 이 태스크의 존재 이유다."""
        got = run_js(f"financialRatios({self._CFS})")
        periods = {r["기간"] for r in got}
        self.assertIn("전기", periods)

    def test_formula_and_inputs_are_returned(self):
        """우리가 만든 숫자는 검증 가능해야 한다."""
        got = run_js(f"financialRatios({self._CFS})")
        r = [x for x in got if x["지표"] == "영업이익률"][0]
        self.assertTrue(r["계산식"])
        self.assertTrue(r["재료"])

    def test_capital_impairment_is_not_reported_when_there_is_none(self):
        """자본총계가 자본금보다 크면 잠식이 아니다.
        공식을 그대로 쓰면 -4302.9% 가 나오는데 그건 정보가 아니다."""
        got = run_js(f"financialRatios({self._CFS})")
        imp = [r for r in got if r["지표"] == "자본잠식률"]
        for r in imp:
            self.assertIsNone(r["값"], f"잠식이 없는데 값을 표기합니다: {r}")

    def test_capital_impairment_is_reported_when_it_exists(self):
        got = run_js('''financialRatios([
          {fs_div:"CFS", sj_div:"BS", account_nm:"자본금", thstrm_amount:"1000"},
          {fs_div:"CFS", sj_div:"BS", account_nm:"자본총계", thstrm_amount:"400"}
        ])''')
        imp = [r for r in got if r["지표"] == "자본잠식률" and r["기간"] == "당기"][0]
        self.assertAlmostEqual(imp["값"], 60.0, places=1)

    def test_consolidated_and_separate_are_not_mixed(self):
        """연결과 별도를 한 계산에 섞으면 거짓이 된다."""
        got = run_js('''financialRatios([
          {fs_div:"CFS", sj_div:"IS", account_nm:"매출액", thstrm_amount:"1000"},
          {fs_div:"CFS", sj_div:"IS", account_nm:"영업이익", thstrm_amount:"100"},
          {fs_div:"OFS", sj_div:"IS", account_nm:"매출액", thstrm_amount:"500"},
          {fs_div:"OFS", sj_div:"IS", account_nm:"영업이익", thstrm_amount:"250"}
        ])''')
        by = {(r["구분"], r["지표"]): r["값"] for r in got if r["지표"] == "영업이익률"}
        self.assertAlmostEqual(by[("연결", "영업이익률")], 10.0, places=1)
        self.assertAlmostEqual(by[("별도", "영업이익률")], 50.0, places=1)

    def test_zero_denominator_yields_null_not_infinity(self):
        got = run_js('''financialRatios([
          {fs_div:"CFS", sj_div:"IS", account_nm:"매출액", thstrm_amount:"0"},
          {fs_div:"CFS", sj_div:"IS", account_nm:"영업이익", thstrm_amount:"100"}
        ])''')
        r = [x for x in got if x["지표"] == "영업이익률"][0]
        self.assertIsNone(r["값"])

    def test_missing_account_yields_null_with_a_reason(self):
        """계정이 없으면 왜 없는지 말해야 한다 — 조용히 빼면 안 된다."""
        got = run_js('''financialRatios([
          {fs_div:"CFS", sj_div:"IS", account_nm:"매출액", thstrm_amount:"1000"}
        ])''')
        r = [x for x in got if x["지표"] == "영업이익률"][0]
        self.assertIsNone(r["값"])
        self.assertTrue(r.get("사유"))

    def test_no_verdict_words_anywhere_in_output(self):
        """계산은 사실, 해석은 판정이다(v0.8.5)."""
        import json as _json
        got = _json.dumps(run_js(f"financialRatios({self._CFS})"), ensure_ascii=False)
        for word in ("악화", "개선", "위험", "주의", "양호", "부실"):
            self.assertNotIn(word, got, f"판정 어휘 '{word}'")


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestDividendVsIncome(unittest.TestCase):
    """SE-4f Task 4 — dividends(alotMatter)의 se 항목 중 이미 같은 백만원
    단위로 나란히 있는 "현금배당금총액"과 "당기순이익"을 사업연도·
    보고서구분별로 묶는다(task-4-brief.md: "섹션 간 조인이 필요 없습니다").
    실측(2026-07-28, 삼성전자 corp_code=00126380, rcept_no=20250311001085,
    bsns_year=2024, reprt_code=11011)과 같은 se 문자열·값을 그대로 쓴다 —
    "픽스처는 실제 API 응답 형태로"(브리프 검증 요구).
    """

    _SAMSUNG_2024 = [
        {"bsns_year": "2024", "reprt_code": "11011", "se": "주당액면가액(원)",
         "thstrm": "100"},
        {"bsns_year": "2024", "reprt_code": "11011", "se": "현금배당금총액(백만원)",
         "thstrm": "9,810,767"},
        {"bsns_year": "2024", "reprt_code": "11011", "se": "(연결)당기순이익(백만원)",
         "thstrm": "33,621,363"},
        {"bsns_year": "2024", "reprt_code": "11011", "se": "(별도)당기순이익(백만원)",
         "thstrm": "23,582,565"},
        {"bsns_year": "2024", "reprt_code": "11011", "se": "주식배당금총액(백만원)",
         "thstrm": "-"},
        {"bsns_year": "2024", "reprt_code": "11011", "se": "(연결)현금배당성향(%)",
         "thstrm": "29.20"},
    ]

    def test_pairs_dividend_and_net_income_for_same_report(self):
        got = run_js(f"dividendVsIncome({json.dumps(self._SAMSUNG_2024, ensure_ascii=False)})")
        self.assertEqual(len(got), 1)
        row = got[0]
        self.assertEqual(row["bsns_year"], "2024")
        self.assertEqual(row["reprt_code"], "11011")
        self.assertEqual(row["현금배당금총액(백만원)"], 9810767)
        self.assertEqual(row["(연결)당기순이익(백만원)"], 33621363)
        self.assertEqual(row["(별도)당기순이익(백만원)"], 23582565)

    def test_dash_value_is_null_not_zero(self):
        """"주식배당금총액"이 "-"(DART 무값 표기)이면 0이 아니라 null이어야
        한다 — 0으로 채우면 "실제로 0이었다"는 거짓말이 된다(numeric() 주석
        원칙과 같다)."""
        got = run_js(f"dividendVsIncome({json.dumps(self._SAMSUNG_2024, ensure_ascii=False)})")
        self.assertIsNone(got[0]["주식배당금총액(백만원)"])

    def test_percent_field_is_kept_as_number(self):
        got = run_js(f"dividendVsIncome({json.dumps(self._SAMSUNG_2024, ensure_ascii=False)})")
        self.assertAlmostEqual(got[0]["(연결)현금배당성향(%)"], 29.2, places=1)

    def test_no_dividend_record_produces_no_row(self):
        """엔켐처럼 현금배당금총액이 "-"인 회사는 이 비교가 발화하지 않는다
        (브리프: "엔켐은 배당이 없습니다 … 배당하는 회사를 직접 찾아 확인").
        빈 배열이지 숨기는 게 아니라 비교할 배당액 자체가 없는 것이다."""
        records = [
            {"bsns_year": "2025", "reprt_code": "11011", "se": "현금배당금총액(백만원)",
             "thstrm": "-"},
            {"bsns_year": "2025", "reprt_code": "11011", "se": "(연결)당기순이익(백만원)",
             "thstrm": "-142,974"},
        ]
        got = run_js(f"dividendVsIncome({json.dumps(records, ensure_ascii=False)})")
        self.assertEqual(got, [])

    def test_separates_rows_by_report_code_within_same_year(self):
        """같은 사업연도라도 분기 보고서마다 다른 보고이므로 한 행으로
        뭉치지 않는다(dividends는 fund_usage와 달리 reprt_code가 정규화
        과정에서 탈락하지 않는다 — 위 CHART_SPECS.dividends 주석 참고)."""
        records = [
            {"bsns_year": "2025", "reprt_code": "11013", "se": "현금배당금총액(백만원)",
             "thstrm": "1,000,000"},
            {"bsns_year": "2025", "reprt_code": "11013", "se": "(연결)당기순이익(백만원)",
             "thstrm": "5,000,000"},
            {"bsns_year": "2025", "reprt_code": "11011", "se": "현금배당금총액(백만원)",
             "thstrm": "2,000,000"},
            {"bsns_year": "2025", "reprt_code": "11011", "se": "(연결)당기순이익(백만원)",
             "thstrm": "9,000,000"},
        ]
        got = run_js(f"dividendVsIncome({json.dumps(records, ensure_ascii=False)})")
        self.assertEqual(len(got), 2)
        by_reprt = {r["reprt_code"]: r for r in got}
        self.assertEqual(by_reprt["11013"]["현금배당금총액(백만원)"], 1000000)
        self.assertEqual(by_reprt["11011"]["현금배당금총액(백만원)"], 2000000)

    def test_not_an_array_returns_empty(self):
        self.assertEqual(run_js("dividendVsIncome(null)"), [])
        self.assertEqual(run_js("dividendVsIncome({})"), [])

    def test_no_verdict_words(self):
        import json as _json
        got = _json.dumps(
            run_js(f"dividendVsIncome({json.dumps(self._SAMSUNG_2024, ensure_ascii=False)})"),
            ensure_ascii=False,
        )
        for word in ("부족", "부적절", "의심", "위험", "과다", "여력"):
            self.assertNotIn(word, got, f"판정 어휘 '{word}'")


@unittest.skipUnless(_NODE, "node가 없어 ui.js의 실제 렌더 결과를 검증할 수 없습니다")
class TestDividendVsIncomeRenderWiring(unittest.TestCase):
    """dividendVsIncome이 정의만 있고 renderSection이 부르지 않는 사고를
    막는다 — "정의만 있고 부르는 곳이 없다"는 이 저장소에서 이미 다섯 번
    난 사고 유형이다(브리프 참고). sectionBlocks 단독 검증으로는 이
    호출부 배선 누락을 못 잡는다."""

    _RECORDS = [
        {"bsns_year": "2024", "reprt_code": "11011", "se": "현금배당금총액(백만원)",
         "thstrm": "9,810,767"},
        {"bsns_year": "2024", "reprt_code": "11011", "se": "(연결)당기순이익(백만원)",
         "thstrm": "33,621,363"},
    ]

    def test_derived_block_title_is_rendered(self):
        got = run_render_section('"dividends"', json.dumps(self._RECORDS, ensure_ascii=False))
        self.assertIn("배당 vs 당기순이익 (사실 비교)", got["titles"])

    def test_formatted_amounts_appear_in_cells(self):
        got = run_render_section('"dividends"', json.dumps(self._RECORDS, ensure_ascii=False))
        cells = got["cells"]
        self.assertIn("9,810,767", cells)
        self.assertIn("33,621,363", cells)

    def test_original_table_is_not_removed(self):
        """새 표기는 표 위에 얹는 것이지 원본 표를 지우는 게 아니다
        (전역 제약: "표를 없애지 않습니다")."""
        got = run_render_section('"dividends"', json.dumps(self._RECORDS, ensure_ascii=False))
        cells = got["cells"]
        self.assertIn("현금배당금총액(백만원)", cells)  # 원본 표의 se 열 값

    def test_no_block_when_no_dividend(self):
        records = [{"bsns_year": "2025", "reprt_code": "11011", "se": "현금배당금총액(백만원)",
                    "thstrm": "-"}]
        got = run_render_section('"dividends"', json.dumps(records, ensure_ascii=False))
        self.assertNotIn("배당 vs 당기순이익 (사실 비교)", got["titles"])


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestFundPlanChanges(unittest.TestCase):
    """SE-4f Task 7 — 같은 조달 건(같은 pay_de·같은 plan_useprps)의
    계획 금액(plan_amount)이 보고 시점마다 다르게 보고된 사실을 뽑는다
    (task-7-brief.md). 2026-07-28 엔켐 실측(corp_code=01011526,
    bsns_year=2022, pssrpCptalUseDtls.json, pay_de=2021.10.26)을 그대로
    쓴다: 1분기 보고(11013)는 운영자금 계획 342.91억(34,291,000,000),
    반기(11012)·3분기(11014)·사업보고서(11011)는 352.91억(35,291,000,000)
    이었다 — 브리프가 말한 그 값 그대로다."""

    def test_detects_differing_plan_amount_for_same_fund_event(self):
        records = [
            {"kind": "public", "year": 2022, "pay_de": "2021.10.26",
             "plan_useprps": "운영자금", "plan_amount": "34,291,000,000"},
            {"kind": "public", "year": 2022, "pay_de": "2021.10.26",
             "plan_useprps": "운영자금", "plan_amount": "35,291,000,000"},
        ]
        got = run_js(f"fundPlanChanges({json.dumps(records, ensure_ascii=False)})")
        self.assertEqual(len(got), 1)
        change = got[0]
        self.assertEqual(change["pay_de"], "2021.10.26")
        self.assertEqual(change["plan_useprps"], "운영자금")
        self.assertEqual(change["amounts"], [34291000000, 35291000000])

    def test_identical_repeated_amount_is_not_a_change(self):
        """엔켐 사업보고서(11011) 실측처럼 같은 건이 두 번 중복 수집돼도
        값 자체가 같으면 계획이 바뀐 게 아니다(리뷰 지적: 반복 수집 자체는
        오류가 아니다 — 위 fund_usage 안내문과 같은 원칙)."""
        records = [
            {"kind": "public", "year": 2022, "pay_de": "2021.10.26",
             "plan_useprps": "시설자금", "plan_amount": "13,082,000,000"},
            {"kind": "public", "year": 2022, "pay_de": "2021.10.26",
             "plan_useprps": "시설자금", "plan_amount": "13,082,000,000"},
        ]
        got = run_js(f"fundPlanChanges({json.dumps(records, ensure_ascii=False)})")
        self.assertEqual(got, [])

    def test_different_purpose_is_not_grouped_together(self):
        records = [
            {"kind": "public", "year": 2022, "pay_de": "2021.10.26",
             "plan_useprps": "운영자금", "plan_amount": "34,291,000,000"},
            {"kind": "public", "year": 2022, "pay_de": "2021.10.26",
             "plan_useprps": "기타", "plan_amount": "47,657,000,000"},
        ]
        got = run_js(f"fundPlanChanges({json.dumps(records, ensure_ascii=False)})")
        self.assertEqual(got, [])

    def test_different_pay_de_is_not_grouped_together(self):
        records = [
            {"kind": "public", "year": 2021, "pay_de": "2021.10.26",
             "plan_useprps": "운영자금", "plan_amount": "34,291,000,000"},
            {"kind": "public", "year": 2022, "pay_de": "2022.05.01",
             "plan_useprps": "운영자금", "plan_amount": "35,291,000,000"},
        ]
        got = run_js(f"fundPlanChanges({json.dumps(records, ensure_ascii=False)})")
        self.assertEqual(got, [])

    def test_records_missing_pay_de_or_purpose_are_skipped(self):
        records = [
            {"kind": "public", "year": 2022, "pay_de": "", "plan_useprps": "운영자금",
             "plan_amount": "1"},
            {"kind": "public", "year": 2022, "pay_de": "2021.10.26", "plan_useprps": "",
             "plan_amount": "2"},
        ]
        got = run_js(f"fundPlanChanges({json.dumps(records, ensure_ascii=False)})")
        self.assertEqual(got, [])

    def test_not_an_array_returns_empty(self):
        self.assertEqual(run_js("fundPlanChanges(null)"), [])
        self.assertEqual(run_js("fundPlanChanges({})"), [])

    def test_no_verdict_words(self):
        import json as _json
        records = [
            {"kind": "public", "year": 2022, "pay_de": "2021.10.26",
             "plan_useprps": "운영자금", "plan_amount": "34,291,000,000"},
            {"kind": "public", "year": 2022, "pay_de": "2021.10.26",
             "plan_useprps": "운영자금", "plan_amount": "35,291,000,000"},
        ]
        got = _json.dumps(
            run_js(f"fundPlanChanges({json.dumps(records, ensure_ascii=False)})"),
            ensure_ascii=False,
        )
        for word in ("의심", "유용", "부정", "위험"):
            self.assertNotIn(word, got, f"판정 어휘 '{word}'")


@unittest.skipUnless(_NODE, "node가 없어 ui.js의 실제 렌더 결과를 검증할 수 없습니다")
class TestFundPlanChangesRenderWiring(unittest.TestCase):
    """fundPlanChanges가 정의만 있고 renderSection이 부르지 않는 사고를
    막는다(위 TestDividendVsIncomeRenderWiring과 같은 이유)."""

    _RECORDS = [
        {"kind": "public", "year": 2022, "tm": "-", "pay_de": "2021.10.26",
         "pay_amount": None, "plan_useprps": "운영자금", "plan_amount": "34,291,000,000",
         "real_dtls_cn": "", "real_dtls_amount": None, "dffrnc_resn": "", "flags": []},
        {"kind": "public", "year": 2022, "tm": "-", "pay_de": "2021.10.26",
         "pay_amount": None, "plan_useprps": "운영자금", "plan_amount": "35,291,000,000",
         "real_dtls_cn": "", "real_dtls_amount": None, "dffrnc_resn": "", "flags": []},
    ]

    def test_derived_block_title_is_rendered(self):
        got = run_render_section('"fund_usage"', json.dumps(self._RECORDS, ensure_ascii=False))
        self.assertIn("계획 금액 변경 (사실 표기)", got["titles"])

    def test_both_amounts_appear_formatted(self):
        got = run_render_section('"fund_usage"', json.dumps(self._RECORDS, ensure_ascii=False))
        cells = " ".join(got["cells"])
        self.assertIn("342.9억", cells)
        self.assertIn("352.9억", cells)

    def test_existing_note_and_table_are_not_removed(self):
        """새 표기는 표 위에 얹는 것 — 기존 fund_usage 안내문과 원본 표
        (전역 제약: "표를 없애지 않습니다")를 지우지 않는다."""
        got = run_render_section('"fund_usage"', json.dumps(self._RECORDS, ensure_ascii=False))
        notes = " ".join(got["notes"])
        self.assertIn("같은 회차가 여러 행으로 나오는 것은 오류가 아닙니다", notes)
        self.assertIn("운영자금", got["cells"])  # 원본 표의 plan_useprps 열 값

    def test_no_block_when_amounts_identical(self):
        records = [
            {"kind": "public", "year": 2022, "pay_de": "2021.10.26",
             "plan_useprps": "시설자금", "plan_amount": "13,082,000,000", "flags": []},
        ]
        got = run_render_section('"fund_usage"', json.dumps(records, ensure_ascii=False))
        self.assertNotIn("계획 금액 변경 (사실 표기)", got["titles"])


if __name__ == "__main__":
    unittest.main()

