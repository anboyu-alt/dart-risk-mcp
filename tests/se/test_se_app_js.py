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
        expected = {s.key for s in STAGE1_SPECS} - {"company_info"}  # 헤더는 별도
        self.assertEqual(expected - shown, set(),
                         "화면에 안 나오는 섹션이 있습니다")
        self.assertEqual(shown - expected, set(),
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
        """2단 `doc:<rcept_no>` 키처럼 SECTION_GROUPS에 없는 키도 어딘가에는
        나와야 한다 — 그룹이 없다고 사라지면 안 된다.
        """
        got = run_js('groupTitleFor("doc:20240301000001")')
        self.assertEqual(got, "기타")

    def test_group_order_follows_definition_order(self):
        got = [run_js(f'groupOrderIndex("{t}")') for t in
               ("자금", "재무", "지배구조", "감사·부실")]
        self.assertEqual(got, sorted(got), "그룹 순서가 정의 순서를 따르지 않습니다")

    def test_unknown_group_sorts_after_all_known_groups(self):
        known_max = max(
            run_js(f'groupOrderIndex("{t}")')
            for t in ("자금", "재무", "지배구조", "감사·부실")
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


if __name__ == "__main__":
    unittest.main()

