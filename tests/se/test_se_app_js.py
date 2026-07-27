"""app.js 순수 함수 검증 — node 서브프로세스로 실제 실행한다.

브라우저 로직을 테스트 밖에 두면 이 저장소의 유일한 품질 장치인 pytest가
닿지 않는다. app.js는 DOM도 네트워크도 만지지 않는 순수 함수만 담으므로
node로 그대로 부를 수 있다.
"""
import json
import pathlib
import shutil
import subprocess
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_APP = _ROOT / "docs" / "tool" / "se" / "app.js"
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
class TestToTable(unittest.TestCase):
    def test_list_of_records_becomes_rows(self):
        got = run_js('toTable([{a:1,b:2},{a:3,b:4}])')
        self.assertEqual(got["rows"], [["1", "2"], ["3", "4"]])

    def test_columns_union_covers_ragged_records(self):
        """레코드마다 필드가 다를 수 있다. 어느 것도 사라지면 안 된다."""
        got = run_js('toTable([{a:1},{b:2}])')
        self.assertEqual(sorted(got["columns"]), ["a", "b"])

    def test_unknown_field_keeps_raw_key_as_header(self):
        """라벨이 없다고 열을 숨기면 데이터가 조용히 사라진다."""
        got = run_js('toTable([{wholly_unknown_field: "x"}])')
        self.assertIn("wholly_unknown_field", got["columns"])

    def test_known_field_uses_korean_label(self):
        got = run_js('toTable([{rcept_no: "20240301000001"}])')
        self.assertIn("접수번호", got["columns"])

    def test_single_dict_becomes_one_row(self):
        got = run_js('toTable({a:1})')
        self.assertEqual(got["rows"], [["1"]])

    def test_empty_value_is_null(self):
        for expr in ("toTable([])", "toTable(null)", "toTable({})"):
            self.assertIsNone(run_js(expr), f"{expr}가 표를 만들었습니다")

    def test_nested_value_is_stringified_not_dropped(self):
        got = run_js('toTable([{x: {deep: 1}}])')
        self.assertNotEqual(got["rows"][0][0], "")

    def test_null_cell_becomes_empty_string_not_the_word_null(self):
        got = run_js('toTable([{a: null}])')
        self.assertEqual(got["rows"][0][0], "")

    def test_zero_and_false_are_not_blanked(self):
        """0과 false는 '없음'이 아니라 유효한 값이다.

        cell()을 `v ? String(v) : ""` 같은 truthy 체크로 바꾸면 0과 false가
        빈 칸이 된다 — 이 테스트가 그 회귀를 잡아야 한다.
        """
        got = run_js('toTable([{a: 0, b: false}])')
        self.assertEqual(got["rows"], [["0", "false"]])

    def test_non_object_list_items_are_not_dropped(self):
        """리스트 안 비객체 항목(문자열 등)이 흔적 없이 사라지면 안 된다.

        toTable([{a:1},"note",{b:2}])는 레코드 3개인데 예전엔 2행이 됐다
        (문자열 항목이 필터링으로 사라짐).
        """
        got = run_js('toTable([{a:1},"note",{b:2}])')
        self.assertEqual(len(got["rows"]), 3, "비객체 항목이 사라졌습니다")
        flat = [cell for row in got["rows"] for cell in row]
        self.assertIn("note", flat, "문자열 항목의 내용이 화면 어디에도 없습니다")

    def test_scalar_string_value_is_not_null(self):
        """toTable("문자열")이 null이면 화면은 '표시할 데이터가 없습니다'라고
        말한다 — 데이터가 있는데 없다고 하는 것이다.
        """
        got = run_js('toTable("어떤 문자열")')
        self.assertIsNotNone(got)
        flat = [cell for row in got["rows"] for cell in row]
        self.assertIn("어떤 문자열", flat)

    def test_list_of_scalars_is_not_null(self):
        got = run_js('toTable(["a","b"])')
        self.assertIsNotNone(got)
        flat = [cell for row in got["rows"] for cell in row]
        self.assertEqual(sorted(flat), ["a", "b"])

    def test_label_lookup_ignores_prototype_keys(self):
        """LABELS가 프로토타입이 있는 일반 객체면 "toString"·"constructor"
        같은 키가 Object.prototype 메서드로 새어나간다 — 컬럼 헤더가 함수
        객체가 되고(JSON 직렬화 시 배열 안 함수는 null이 된다), 실제로
        확인된 버그다.
        """
        got = run_js('toTable([{toString: "x", constructor: "y"}])')
        self.assertIn("toString", got["columns"])
        self.assertIn("constructor", got["columns"])
        self.assertNotIn(None, got["columns"], "헤더가 함수로 새어나갔습니다")


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
        """indicators처럼 하위 구조 없는 순수 스칼라 dict는 굳이 안 쪼갠다."""
        got = run_js('sectionBlocks({순이익률: 12.3, 부채비율: 45.6})')
        self.assertEqual(len(got), 1)
        self.assertIsNone(got[0]["title"])
        self.assertEqual(got[0]["table"]["rows"], [["12.3", "45.6"]])

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

    def test_unknown_status_is_treated_as_weakest(self):
        """모르는 값을 강한 쪽으로 보여주는 실수는 허용되지 않는다."""
        for bad in ('""', '"확인됨"', "null", "123", '["verified"]'):
            got = run_js(f'actorLine({{name:"홍길동", status:{bad}, companies:[]}})')
            self.assertIn("동명이인", got["warn"],
                          f"status={bad} 인데 경고가 없습니다")

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


if __name__ == "__main__":
    unittest.main()
