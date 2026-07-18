/**
 * DART CORS 릴레이 — Vercel 서버리스 함수 (서울 리전 icn1 고정)
 *
 * relay/worker.js(Cloudflare)와 동일 계약. DART(opendart.fss.or.kr)가
 * 해외 IP 대역을 차단해 Cloudflare 경유가 522로 실패하므로(2026-07 실측),
 * 한국 리전에서 나가는 이 구현을 기본 릴레이로 사용한다.
 * 리전 고정은 저장소 루트 vercel.json의 "regions": ["icn1"].
 *
 * 신뢰 경계: 키·파라미터·응답을 저장하거나 로그로 남기지 않는 무상태 통과.
 * 허용 목록 밖 엔드포인트·GET 외 메서드는 403.
 */

const ALLOWED_ENDPOINTS = new Set(["list.json", "company.json"]);

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
    res.status(upstream.status).send(body);
  } catch (e) {
    res.status(502).json({ error: "upstream" });
  }
}
