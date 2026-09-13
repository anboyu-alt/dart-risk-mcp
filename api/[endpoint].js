/**
 * DART CORS 릴레이 — Vercel 서버리스 함수 (서울 리전 icn1 고정)
 *
 * relay/worker.js(Cloudflare)와 동일 계약. DART(opendart.fss.or.kr)가
 * 해외 IP 대역을 차단해 Cloudflare 경유가 522로 실패하므로(2026-07 실측),
 * 한국 리전에서 나가는 이 구현을 기본 릴레이로 사용한다.
 * 리전 고정은 저장소 루트 vercel.json의 "regions": ["icn1"].
 *
 * 신뢰 경계:
 * - 키·파라미터·응답을 **저장하거나 로그로 남기지 않는다.**
 * - 허용 목록 밖 엔드포인트·GET 외 메서드는 403.
 * - 서버 키 경로에서만 날짜별 **숫자 카운터** 둘을 올린다(tool_server/quota.py의
 *   키 형식과 같다). 어느 방문자가 어느 회사를 봤는지는 저장하지 않는다.
 *
 * ## 서버 키 주입 (2026-09-13)
 *
 * 브라우저가 `crtfc_key`를 보내지 않았을 때만 환경변수 `DART_API_KEY`로 채운다.
 * 키가 있으면 그것을 쓴다 — 환경변수가 사용자의 선택을 덮어쓰지 않는다
 * (scripts/dev_relay.py의 `_with_key`와 같은 우선순위).
 *
 * 이 파일에 서버 키를 두는 것은 오래 금지돼 있었다(*"그 주소를 아는 누구나
 * 제작자의 한도를 쓴다"*). 그 전제를 쿼터가 대신 막는다 —
 * `tests/test_dev_relay_env_key.py`가 **서버 키가 있으면 쿼터 검사도 반드시
 * 있을 것**으로 경계를 다시 세웠다. 쿼터 저장소가 붙지 않은 relay/worker.js에는
 * 여전히 서버 키를 두지 않는다.
 *
 * OpenDART 이용약관 제19조 2항("인증키를 제3자에게 이용하게 해서는 안 됩니다")은
 * 키가 명의자 아닌 사람 손에 넘어가는 것을 금지한다. 키가 서버 밖으로 나가지
 * 않는 이 구조는 해당하지 않으며, FAQ가 재배포·재가공 서비스를 허용한다.
 */

const ALLOWED_ENDPOINTS = new Set([
  "list.json",
  "company.json",
  "fnlttSinglAcnt.json",              // 주요 재무계정 (뷰어 심화 블록)
  "accnutAdtorNmNdAdtOpinion.json",   // 감사인·감사의견 (뷰어 심화 블록)
  "exctvSttus.json",                  // 임원현황 (뷰어 겸직 비교 모드)
  "elestock.json",                    // 임원·주요주주 소유보고 (뷰어 지분 변동 블록)
  "alotMatter.json",                  // 배당에 관한 사항 (뷰어 배당 유출 블록)
  "pssrpCptalUseDtls.json",           // 공모자금 사용 내역 (뷰어 자금 체인 블록)
  "prvsrpCptalUseDtls.json",          // 사모자금 사용 내역 (뷰어 자금 체인 블록)
  "otrCprInvstmntSttus.json",         // 타법인 출자현황 (뷰어 종속회사 유출 사실 병기)
  "fnlttSinglAcntAll.json",           // 전체 계정과목 (뷰어 회전율 3기간 블록)
  "irdsSttus.json",                   // 증자(감자) 현황 (뷰어 희석 블록)
  "stockTotqySttus.json",             // 주식의 총수 (희석 비중의 분모)
  "cvbdIsDecsn.json",                 // 전환사채권 발행결정 (메자닌 조건)
  "bdwtIsDecsn.json",                 // 신주인수권부사채권 발행결정
  "exbdIsDecsn.json",                 // 교환사채권 발행결정
  "cprndNrdmpBlce.json",                   // 회사채 미상환 잔액
  "srtpdPsndbtNrdmpBlce.json",             // 단기사채 미상환 잔액
  "entrprsBilScritsNrdmpBlce.json",        // 기업어음 미상환 잔액
  "newCaplScritsNrdmpBlce.json",           // 신종자본증권 미상환 잔액
  "cndlCaplScritsNrdmpBlce.json",          // 조건부자본증권 미상환 잔액
  "adtServcCnclsSttus.json",               // 감사용역 계약 체결 현황
  "accnutAdtorNonAdtServcCnclsSttus.json", // 비감사용역 계약 체결 현황
]);

/**
 * 신선도가 필요해 캐시하지 않는 엔드포인트.
 *
 * 스캔 1회 30~45콜 중 이 넷이 4~13콜이고 나머지 27~33콜은 `bsns_year` 축이다
 * (정기보고서에서 나오므로 하루 안에 바뀌지 않는다). **무거운 쪽이 신선도를
 * 요구하지 않아** 캐시와 신선도를 동시에 만족시킬 수 있다.
 *
 * 공시는 수시로 접수되므로 목록과 메자닌 발행결정은 매번 실호출한다.
 */
const NO_CACHE_ENDPOINTS = new Set([
  "list.json",
  "cvbdIsDecsn.json",
  "bdwtIsDecsn.json",
  "exbdIsDecsn.json",
]);

const CACHE_SECONDS = 21600; // 6시간 — 정기보고서 제출 시점에만 값이 바뀐다

// tool_server/quota.py의 상수와 같은 값이어야 한다. 두 런타임(JS 릴레이 ·
// Python 함수)이 같은 Redis 키를 쓰므로 어긋나면 한쪽만 막힌다.
const DAILY_GLOBAL_CAP = 16000;
const DAILY_IP_SCANS = 25;
const QUOTA_TTL = 48 * 3600;

/** 오늘 날짜(KST, YYYYMMDD). UTC로 세면 화면의 "오늘"과 어긋난다. */
function kstDay() {
  return new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10).replace(/-/g, "");
}

function clientIp(req) {
  const chain = (req.headers["x-forwarded-for"] || "").trim();
  if (!chain) return null;
  return chain.split(",")[0].trim() || null;
}

/**
 * 스캔 한 번의 시작인가 — `list.json`의 첫 페이지.
 *
 * 릴레이는 개별 호출만 보므로 "스캔"이라는 단위를 직접 알 수 없다. 모든 스캔이
 * 공시 목록 1페이지에서 시작하므로 그것을 신호로 쓴다. 2페이지 이후는 같은
 * 스캔의 연속이라 세지 않는다.
 */
function isScanStart(endpoint, params) {
  if (endpoint !== "list.json") return false;
  const p = params.page_no;
  return !p || String(p) === "1";
}

/**
 * 전역·IP 카운터를 올리고 통과 여부를 돌려준다.
 *
 * 저장소가 없거나 실패하면 통과("allow")다 — 판정할 수 없는 것을 거절로 바꾸지
 * 않는다. 그때 예산을 지키는 것은 DART 자신의 020 응답이다.
 */
async function checkQuota(req, endpoint, params) {
  const url = (process.env.UPSTASH_REDIS_REST_URL || "").replace(/\/+$/, "");
  const token = process.env.UPSTASH_REDIS_REST_TOKEN || "";
  if (!url || !token) return "allow";

  const day = kstDay();
  const ip = clientIp(req);
  const scanStart = isScanStart(endpoint, params) && !!ip;
  const cmds = [["INCR", `q:g:${day}`], ["EXPIRE", `q:g:${day}`, String(QUOTA_TTL)]];
  if (scanStart) {
    cmds.push(["INCR", `q:s:${ip}:${day}`], ["EXPIRE", `q:s:${ip}:${day}`, String(QUOTA_TTL)]);
  }

  let out;
  try {
    const r = await fetch(`${url}/pipeline`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify(cmds),
      signal: AbortSignal.timeout(2000),
    });
    if (!r.ok) return "allow";
    out = await r.json();
  } catch (e) {
    return "allow";
  }
  if (!Array.isArray(out) || !out.length) return "allow";

  const num = (entry) => {
    const v = entry && typeof entry === "object" ? entry.result : null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  };
  const total = num(out[0]);
  if (total !== null && total > DAILY_GLOBAL_CAP) return "global";
  if (scanStart && out.length >= 3) {
    const scans = num(out[2]);
    if (scans !== null && scans > DAILY_IP_SCANS) return "ip";
  }
  return "allow";
}

/**
 * 거절 사유별 문구.
 *
 * ⚠ 전역 상한과 IP 상한을 같은 문구로 적으면 안 된다 — "남이 다 썼다"와
 * "내가 다 썼다"는 다른 사실이고, 섞이면 방문자가 남의 소진을 자기 탓으로
 * 오해한다.
 */
function quotaPayload(reason) {
  if (reason === "global") {
    return {
      status: "quota",
      quota: "global",
      message: "공용 조회가 오늘 한도에 도달했습니다. 내일 다시 열리며, " +
               "지금 보시려면 DART 인증키를 입력하세요.",
    };
  }
  return {
    status: "quota",
    quota: "ip",
    message: "이 회선에서 오늘 무료 조회 몫을 모두 쓰셨습니다. " +
             "DART 인증키를 입력하면 제한 없이 조회할 수 있습니다.",
  };
}

/**
 * 이 응답을 CDN에 캐시해도 되는가.
 *
 * ⚠ 사용자 키가 실린 요청은 절대 캐시하지 않는다 — 캐시 키에 남의 인증키가
 * 섞인다. 서버 키 경로만 캐시 대상이고, 그때는 URL에 키가 없어 안전하다
 * (api/doc.py가 이미 같은 논리로 s-maxage=86400을 쓴다).
 *
 * ⚠ DART는 오류를 **HTTP 200 본문**으로 준다(020 한도 초과·800 점검). 본문의
 * status를 보고 갈라야 한다. 013(자료 없음)은 정상 부재라 캐시한다 —
 * 이것까지 실패로 세면 캐시가 통째로 무력해진다(CLAUDE.md 「못 받은 결과를
 * 캐시하지 않는다」).
 */
function cacheable(usedServerKey, endpoint, status, body) {
  if (!usedServerKey) return false;
  if (status !== 200) return false;
  if (NO_CACHE_ENDPOINTS.has(endpoint)) return false;
  let dartStatus = "";
  try {
    dartStatus = String((JSON.parse(body) || {}).status || "");
  } catch (e) {
    return false; // JSON이 아니면 무엇인지 모른다 — 캐시하지 않는다
  }
  return dartStatus === "000" || dartStatus === "013";
}

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  res.setHeader("Cache-Control", "no-store");

  if (req.method === "OPTIONS") {
    res.status(204).end();
    return;
  }
  const { endpoint, ...params } = req.query;
  if (req.method !== "GET" || !ALLOWED_ENDPOINTS.has(endpoint)) {
    res.status(403).json({ error: "forbidden" });
    return;
  }

  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    usp.set(k, Array.isArray(v) ? v[0] : v);
  }

  // 브라우저가 키를 보내지 않았을 때만 서버 키를 쓴다.
  const browserKey = (usp.get("crtfc_key") || "").trim();
  let usedServerKey = false;
  if (!browserKey) {
    const serverKey = (process.env.DART_API_KEY || "").trim();
    if (serverKey) {
      usp.set("crtfc_key", serverKey);
      usedServerKey = true;
    }
  }

  // 쿼터는 서버 키 경로에만 건다 — 자기 키를 쓰는 사람은 자기 한도를 쓰므로
  // 우리가 막을 이유가 없다.
  if (usedServerKey) {
    const verdict = await checkQuota(req, endpoint, params);
    if (verdict !== "allow") {
      res.status(429).json(quotaPayload(verdict));
      return;
    }
  }

  try {
    const upstream = await fetch(
      `https://opendart.fss.or.kr/api/${endpoint}?${usp}`,
      { headers: { Accept: "application/json" } },
    );
    const body = await upstream.text();
    res.setHeader(
      "Content-Type",
      upstream.headers.get("content-type") || "application/json",
    );
    if (cacheable(usedServerKey, endpoint, upstream.status, body)) {
      // 브라우저에는 캐시하지 않는다(새로고침이 먹히지 않으면 혼란스럽다).
      // CDN에만 둔다.
      res.setHeader("Cache-Control", `public, max-age=0, s-maxage=${CACHE_SECONDS}`);
    }
    res.status(upstream.status).send(body);
  } catch (e) {
    res.status(502).json({ error: "upstream" });
  }
}
