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
 *
 * ## `?quota=1` — 쿼터가 살아 있는지 본다 (2026-09-13)
 *
 * 쿼터는 저장소에 못 닿으면 **조용히 통과시킨다**(가용성을 깎지 않는다는 설계).
 * 그런데 그러면 Upstash 한도를 넘겨 모든 호출이 거절당해도 화면에 아무것도
 * 나타나지 않고 **예산 방어만 사라진다** — 이 레포가 반복해서 걷어내 온
 * 「조용한 실패」와 같은 모양이다. 운영자가 아무 때나 열어 확인할 수 있게 한다.
 *
 * ⚠ **기본 응답에는 넣지 않는다.** 뷰어가 부팅마다 이 경로를 부르므로, 기본에
 * 넣으면 방문자 수만큼 Upstash 명령이 늘고 부팅도 그만큼 느려진다. 쿼터 상태는
 * 운영자만 보면 되는 값이라 쿼리 파라미터로 가른다.
 *
 * ⚠ **`INCR`가 아니라 `GET`이다** — 상태를 보는 행위가 카운터를 올리면 안 된다.
 *
 * ⚠ **「안 켰다」와 「켰는데 못 닿았다」를 가른다**(`configured` / `reachable`).
 * 둘을 뭉치면 설정을 빠뜨린 것과 한도를 넘긴 것이 같은 화면으로 보인다.
 */

// api/[endpoint].js·tool_server/quota.py와 **같은 값·같은 키 형식**이어야 한다.
// 세 곳이 갈리면 이 화면이 실제와 다른 카운터를 읽는다.
// tests/test_viewer_quota.py가 셋을 함께 대조한다.
const DAILY_GLOBAL_CAP = 16000;

/** 오늘 날짜(KST, YYYYMMDD). UTC로 세면 화면의 "오늘"과 어긋난다. */
function kstDay() {
  return new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10).replace(/-/g, "");
}

/**
 * 오늘 전역 카운터를 **읽기만** 한다.
 *
 * 반환: `{configured, reachable, today_calls, daily_cap}`
 * - `configured` — 자격증명이 있는가(없으면 쿼터 자체가 꺼진 상태다)
 * - `reachable`  — 실제로 응답을 받았는가(false면 한도 초과·장애·오타)
 * - `today_calls` — 못 읽었으면 `null`(0이 아니다 — 「없다」와 「모른다」는 다르다)
 */
async function quotaStatus() {
  const url = (process.env.UPSTASH_REDIS_REST_URL || "").replace(/\/+$/, "");
  const token = process.env.UPSTASH_REDIS_REST_TOKEN || "";
  const base = { configured: !!(url && token), reachable: false,
                 today_calls: null, daily_cap: DAILY_GLOBAL_CAP };
  if (!base.configured) return base;

  const day = kstDay();
  try {
    const r = await fetch(`${url}/get/q:g:${day}`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(2000),
    });
    if (!r.ok) return base;                 // 401·429·5xx — 닿지 못했다
    const j = await r.json();
    base.reachable = true;
    // 키가 없으면 result가 null이다 — 오늘 아직 한 건도 안 쓴 정상 상태다.
    const n = Number(j && j.result);
    base.today_calls = Number.isFinite(n) ? n : 0;
  } catch (e) {
    /* 타임아웃·네트워크 — reachable false 그대로 */
  }
  return base;
}

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  res.setHeader("Cache-Control", "no-store");
  if (req.method === "OPTIONS") { res.status(204).end(); return; }
  if (req.method !== "GET") { res.status(405).json({ error: "method" }); return; }

  const body = {
    ok: true,
    server_key: !!(process.env.DART_API_KEY || "").trim(),
    free_scans: 5,
  };
  const want = req.query && req.query.quota;
  if (want && String(want) !== "0") {
    body.quota = await quotaStatus();
  }
  res.status(200).json(body);
}
