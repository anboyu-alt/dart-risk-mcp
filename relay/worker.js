/**
 * DART CORS 릴레이 — Cloudflare Worker
 *
 * 역할: 브라우저(라이브 리스크 도구)가 보낸 DART OpenAPI 요청에
 * CORS 헤더만 붙여 그대로 통과시키는 무상태 관(管)입니다.
 *
 * 하지 않는 것 (신뢰 경계):
 * - API 키·파라미터·응답을 저장하거나 로그로 남기지 않습니다.
 * - 허용 목록 밖 엔드포인트·GET 외 메서드는 403.
 * - 사용자 키는 브라우저 → 이 릴레이 → DART로 통과할 뿐입니다.
 *
 * 배포: relay/README.md 참고 (Cloudflare 대시보드에 이 파일 붙여넣기).
 * 셀프호스트 대안: python scripts/dev_relay.py (동일 계약).
 */

const ALLOWED_ENDPOINTS = new Set([
  "list.json",
  "company.json",
  "fnlttSinglAcnt.json",
  "accnutAdtorNmNdAdtOpinion.json",
  "exctvSttus.json",
  "elestock.json",
  "alotMatter.json",
  "pssrpCptalUseDtls.json",
  "prvsrpCptalUseDtls.json",
  "otrCprInvstmntSttus.json",
  "fnlttSinglAcntAll.json",
  "irdsSttus.json",
  "stockTotqySttus.json",
  "cvbdIsDecsn.json",
  "bdwtIsDecsn.json",
  "exbdIsDecsn.json",
  "cprndNrdmpBlce.json",
  "srtpdPsndbtNrdmpBlce.json",
  "entrprsBilScritsNrdmpBlce.json",
  "newCaplScritsNrdmpBlce.json",
  "cndlCaplScritsNrdmpBlce.json",
  "adtServcCnclsSttus.json",
  "accnutAdtorNonAdtServcCnclsSttus.json",
]);

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Max-Age": "86400",
};

/**
 * KRX Open API 릴레이 — 사용자 본인 키 전용 (GET /api/krx).
 *
 * DART 경로(위)와 다른 라우트다 — 키 전달이 헤더 `X-KRX-Key` → 업스트림
 * `AUTH_KEY`이고, 서버 키·캐시가 없다(약관 제11조 ② — 운영자 키로 받은
 * 시세를 방문자에게 보여 줄 수 없다). `api/krx.js`(Vercel)와 같은 계약.
 *
 * ⚠ Cloudflare에서 KRX가 해외 IP를 막는지는 재지 않았다 — 실패는 502로
 * 두고 뷰어가 `fetchFailHTML`로 밝힌다.
 *
 * **지수(코스피·코스닥, 2026-09-23 추가)**: `api/krx.js`와 같은 계약 — 경로
 * 접두가 다르고(`idx/` — 종목은 `sto/`), `IDX_NM` 정확 일치로 한 행만 고르며
 * `isu`는 받지 않는다. 정규화 키도 다르다(`close`/`fluc_rt`/`mktcap`뿐).
 */
const KRX_STO_BASE = "https://data-dbg.krx.co.kr/svc/apis/sto";
const KRX_IDX_BASE = "https://data-dbg.krx.co.kr/svc/apis/idx";
// core dart_risk_mcp/core/krx_client.py의 KRX_API_IDS.values()·
// KRX_INDEX_API_IDS.values()와 같아야 한다.
const KRX_STOCK_APIS = new Set(["stk_bydd_trd", "ksq_bydd_trd"]);
const KRX_INDEX_APIS = new Set(["kospi_dd_trd", "kosdaq_dd_trd"]);
const KRX_ALLOWED_APIS = new Set([...KRX_STOCK_APIS, ...KRX_INDEX_APIS]);
// core KRX_INDEX_NAMES와 같아야 한다.
const KRX_INDEX_NAMES = { kospi_dd_trd: "코스피", kosdaq_dd_trd: "코스닥" };
const KRX_CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, X-KRX-Key",
  "Access-Control-Max-Age": "86400",
};

function krxToNumber(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const s = String(value).replace(/,/g, "").trim();
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function krxNormalizeRow(date8, raw) {
  return {
    date: date8,
    close: krxToNumber(raw.TDD_CLSPRC),
    fluc_rt: krxToNumber(raw.FLUC_RT),
    volume: krxToNumber(raw.ACC_TRDVOL),
    value: krxToNumber(raw.ACC_TRDVAL),
    mktcap: krxToNumber(raw.MKTCAP),
    list_shrs: krxToNumber(raw.LIST_SHRS),
    sect: (raw.SECT_TP_NM || "").trim() || null,
  };
}

/** core `_normalize_index_row`와 같은 키·값. */
function krxNormalizeIndexRow(date8, raw) {
  return {
    date: date8,
    close: krxToNumber(raw.CLSPRC_IDX),
    fluc_rt: krxToNumber(raw.FLUC_RT),
    mktcap: krxToNumber(raw.MKTCAP),
  };
}

function krxJson(status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      ...KRX_CORS_HEADERS,
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
    },
  });
}

async function handleKrx(request, url) {
  if (request.method !== "GET") {
    return krxJson(403, { ok: false, error: "forbidden" });
  }
  const key = (request.headers.get("X-KRX-Key") || "").trim();
  if (!key) {
    return krxJson(400, { ok: false, error: "missing_key" });
  }
  const api = url.searchParams.get("api") || "";
  const isIndex = KRX_INDEX_APIS.has(api);
  const basDd = url.searchParams.get("basDd") || "";
  const isu = url.searchParams.get("isu") || "";
  if (
    !KRX_ALLOWED_APIS.has(api)
    || !/^\d{8}$/.test(basDd)
    || (!isIndex && !/^\d{6}$/.test(isu))
  ) {
    return krxJson(400, { ok: false, error: "bad_params" });
  }

  let upstream;
  try {
    const base = isIndex ? KRX_IDX_BASE : KRX_STO_BASE;
    upstream = await fetch(`${base}/${api}?basDd=${encodeURIComponent(basDd)}`, {
      headers: { AUTH_KEY: key },
    });
  } catch (e) {
    return krxJson(502, { ok: false, error: "upstream" });
  }
  if (upstream.status === 401) {
    return krxJson(401, { ok: false, error: "unauthorized" });
  }
  if (upstream.status !== 200) {
    return krxJson(502, { ok: false, error: "upstream" });
  }

  let data;
  try {
    data = await upstream.json();
  } catch (e) {
    return krxJson(502, { ok: false, error: "upstream" });
  }
  const rows = data && Array.isArray(data.OutBlock_1) ? data.OutBlock_1 : null;
  if (rows === null) {
    return krxJson(502, { ok: false, error: "upstream" });
  }
  if (!rows.length) {
    return krxJson(200, { ok: true, found: false, empty: true });
  }
  if (isIndex) {
    const row = rows.find((r) => r.IDX_NM === KRX_INDEX_NAMES[api]);
    if (!row) {
      return krxJson(200, { ok: true, found: false, empty: false });
    }
    return krxJson(200, { ok: true, found: true, row: krxNormalizeIndexRow(basDd, row) });
  }
  const row = rows.find((r) => String(r.ISU_CD) === isu);
  if (!row) {
    return krxJson(200, { ok: true, found: false, empty: false });
  }
  return krxJson(200, { ok: true, found: true, row: krxNormalizeRow(basDd, row) });
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === "/api/krx") {
      if (request.method === "OPTIONS") {
        return new Response(null, { status: 204, headers: KRX_CORS_HEADERS });
      }
      return handleKrx(request, url);
    }
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }
    const m = url.pathname.match(/^\/api\/([A-Za-z0-9]+\.json)$/);
    if (request.method !== "GET" || !m || !ALLOWED_ENDPOINTS.has(m[1])) {
      return new Response(JSON.stringify({ error: "forbidden" }), {
        status: 403,
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" },
      });
    }
    const target = new URL("https://opendart.fss.or.kr/api/" + m[1]);
    target.search = url.search;
    const upstream = await fetch(target.toString(), {
      headers: { Accept: "application/json" },
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        ...CORS_HEADERS,
        "Content-Type":
          upstream.headers.get("content-type") || "application/json",
        "Cache-Control": "no-store",
      },
    });
  },
};
