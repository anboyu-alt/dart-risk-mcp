/**
 * KRX Open API 릴레이 — Vercel 서버리스 함수 (서울 리전 icn1 고정)
 *
 * `api/[endpoint].js`(DART)와 별도 라우트다 — 키 전달 방식이 다르고
 * (헤더 `X-KRX-Key` → 업스트림 `AUTH_KEY`), `tests/test_dev_relay_env_key.py`가
 * `api/[endpoint].js`의 문장 순서를 검사하므로 그 파일에 얹지 않는다.
 *
 * **경계는 약관이다.** KRX Open API 이용약관 제11조 ②(제공받은 정보의 제3자
 * 제공 금지) 때문에 운영자 키로 받은 시세를 방문자에게 보여 줄 수 없다. 그래서
 * 이 라우트는 **사용자 본인의 KRX 키**로만 동작한다 — 서버 키 주입이 없고,
 * DART 경로가 가진 쿼터·CDN 캐시도 없다. 응답은 항상 `Cache-Control: no-store`.
 *
 * 시장 전체(하루 단위, 유가 293KB·코스닥 596KB)를 받아 요청받은 종목 **한
 * 행만** 돌려준다 — 브라우저가 그 용량을 직접 받지 않게 하는 것이 이 라우트의
 * 존재 이유다. 아무것도 저장하지 않는다.
 *
 * 계약: GET /api/krx?api={stk_bydd_trd|ksq_bydd_trd|kospi_dd_trd|kosdaq_dd_trd}
 * &basDd=YYYYMMDD&isu=071950(지수는 생략)
 * 헤더 X-KRX-Key(필수) → 업스트림 AUTH_KEY.
 *
 * **지수(코스피·코스닥, 2026-09-23 추가)**: 경로가 종목과 다르다(`svc/apis/idx/...`,
 * 종목은 `svc/apis/sto/...`). 응답은 하루치 **모든 지수**(실측 코스피 54행·
 * 코스닥 40행)이고 첫 행이 「코스피 (외국주포함)」이라 `IDX_NM` **정확 일치**로
 * 「코스피」/「코스닥」 한 행만 고른다(종목이 `ISU_CD`로 한 행만 고르는 것과 같은
 * 이유). `isu`는 지수에서 받지 않는다(있어도 무시). 정규화 키는 종목과 다르다
 * (`close`/`fluc_rt`/`mktcap` — `volume`·`value`·`list_shrs`·`sect`가 없다).
 *
 * 설계: docs/superpowers/specs/2026-09-23-viewer-krx-panel-design.md
 * 「릴레이 계약 (3곳 동일)」절, docs/superpowers/specs/2026-09-23-viewer-market-chart-design.md
 * 「릴레이」절.
 */

const KRX_STO_BASE = "https://data-dbg.krx.co.kr/svc/apis/sto";
const KRX_IDX_BASE = "https://data-dbg.krx.co.kr/svc/apis/idx";

// core dart_risk_mcp/core/krx_client.py의 KRX_API_IDS.values()·
// KRX_INDEX_API_IDS.values()와 같아야 한다(tests/test_viewer_krx_relay.py가 대조).
const STOCK_APIS = new Set(["stk_bydd_trd", "ksq_bydd_trd"]);
const INDEX_APIS = new Set(["kospi_dd_trd", "kosdaq_dd_trd"]);
const ALLOWED_APIS = new Set([...STOCK_APIS, ...INDEX_APIS]);
// core KRX_INDEX_NAMES와 같아야 한다.
const INDEX_NAMES = { kospi_dd_trd: "코스피", kosdaq_dd_trd: "코스닥" };

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, X-KRX-Key",
  "Access-Control-Max-Age": "86400",
};

/** 콤마 제거 후 숫자, 못 읽으면 null — core `_to_number`와 같은 규칙. */
function toNumber(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const s = String(value).replace(/,/g, "").trim();
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

/** core `_normalize_row`와 같은 키·값(8필드 → 7필드, `sect` 빈 문자열→null). */
function normalizeRow(date8, raw) {
  return {
    date: date8,
    close: toNumber(raw.TDD_CLSPRC),
    fluc_rt: toNumber(raw.FLUC_RT),
    volume: toNumber(raw.ACC_TRDVOL),
    value: toNumber(raw.ACC_TRDVAL),
    mktcap: toNumber(raw.MKTCAP),
    list_shrs: toNumber(raw.LIST_SHRS),
    sect: (raw.SECT_TP_NM || "").trim() || null,
  };
}

/** core `_normalize_index_row`와 같은 키·값. 종목 행과 이름을 다르게 둔다 —
 * 지수에는 기준가 조정이 없어 `priceBreaks`류를 재사용하면 안 된다는 뜻이다. */
function normalizeIndexRow(date8, raw) {
  return {
    date: date8,
    close: toNumber(raw.CLSPRC_IDX),
    fluc_rt: toNumber(raw.FLUC_RT),
    mktcap: toNumber(raw.MKTCAP),
  };
}

function qs(v) {
  return Array.isArray(v) ? v[0] : v;
}

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, X-KRX-Key");
  res.setHeader("Cache-Control", "no-store");

  if (req.method === "OPTIONS") {
    res.status(204).end();
    return;
  }
  if (req.method !== "GET") {
    res.status(403).json({ ok: false, error: "forbidden" });
    return;
  }

  const key = String(req.headers["x-krx-key"] || "").trim();
  if (!key) {
    res.status(400).json({ ok: false, error: "missing_key" });
    return;
  }

  const api = qs(req.query.api);
  const basDd = String(qs(req.query.basDd) || "");
  const isIndex = INDEX_APIS.has(api);
  const isu = String(qs(req.query.isu) || "");
  if (
    !ALLOWED_APIS.has(api)
    || !/^\d{8}$/.test(basDd)
    || (!isIndex && !/^\d{6}$/.test(isu))
  ) {
    res.status(400).json({ ok: false, error: "bad_params" });
    return;
  }

  let upstream;
  try {
    upstream = await fetch(
      `${isIndex ? KRX_IDX_BASE : KRX_STO_BASE}/${api}?basDd=${encodeURIComponent(basDd)}`,
      { headers: { AUTH_KEY: key } },
    );
  } catch (e) {
    res.status(502).json({ ok: false, error: "upstream" });
    return;
  }

  if (upstream.status === 401) {
    res.status(401).json({ ok: false, error: "unauthorized" });
    return;
  }
  if (upstream.status !== 200) {
    res.status(502).json({ ok: false, error: "upstream" });
    return;
  }

  let data;
  try {
    data = await upstream.json();
  } catch (e) {
    res.status(502).json({ ok: false, error: "upstream" });
    return;
  }

  const rows = data && Array.isArray(data.OutBlock_1) ? data.OutBlock_1 : null;
  if (rows === null) {
    res.status(502).json({ ok: false, error: "upstream" });
    return;
  }
  if (!rows.length) {
    res.status(200).json({ ok: true, found: false, empty: true });
    return;
  }
  if (isIndex) {
    const row = rows.find((r) => r.IDX_NM === INDEX_NAMES[api]);
    if (!row) {
      res.status(200).json({ ok: true, found: false, empty: false });
      return;
    }
    res.status(200).json({ ok: true, found: true, row: normalizeIndexRow(basDd, row) });
    return;
  }
  const row = rows.find((r) => String(r.ISU_CD) === isu);
  if (!row) {
    res.status(200).json({ ok: true, found: false, empty: false });
    return;
  }
  res.status(200).json({ ok: true, found: true, row: normalizeRow(basDd, row) });
}
