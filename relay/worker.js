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

const ALLOWED_ENDPOINTS = new Set(["list.json", "company.json"]);

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Max-Age": "86400",
};

export default {
  async fetch(request) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }
    const url = new URL(request.url);
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
