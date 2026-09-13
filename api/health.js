/**
 * 릴레이 상태 — `GET /api/health`
 *
 * 뷰어가 부팅 때 한 번 불러 "이 릴레이가 서버 키를 갖고 있는가"를 확인한다
 * (`probeServerKey`). 키 값은 내보내지 않는다 — 있다/없다 불리언 하나뿐이다.
 * 로컬 개발 릴레이(scripts/dev_relay.py)가 먼저 제공하던 계약을 공용 배포에도
 * 둔 것이며, 응답 모양이 같아야 뷰어가 두 환경에서 같게 동작한다.
 *
 * 서버 키가 있으면 키 없는 방문자도 조회할 수 있고, 그 조회는 쿼터
 * (api/[endpoint].js의 checkQuota)를 통과해야 한다.
 */
export default function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  res.setHeader("Cache-Control", "no-store");
  if (req.method === "OPTIONS") { res.status(204).end(); return; }
  if (req.method !== "GET") { res.status(405).json({ error: "method" }); return; }
  res.status(200).json({
    ok: true,
    server_key: !!(process.env.DART_API_KEY || "").trim(),
    free_scans: 5,
  });
}
