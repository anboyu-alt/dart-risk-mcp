# DART CORS 릴레이

라이브 리스크 도구(`docs/tool/`)가 브라우저에서 DART OpenAPI를 호출할 수 있게
하는 초소형 무상태 프록시입니다. DART가 CORS를 허용하지 않아 필요합니다.

**신뢰 경계**: 릴레이는 사용자의 API 키·요청·응답을 저장하거나 기록하지
않습니다. 허용된 2개 엔드포인트(`list.json`, `company.json`)의 GET 요청에
CORS 헤더만 붙여 통과시킵니다. 코드는 전부 공개돼 있고(`api/[endpoint].js`,
`relay/worker.js`), 아래 셀프호스트 방법으로 직접 띄워 쓸 수도 있습니다.

## ⚠️ 중요 — 릴레이는 한국 리전에서 실행돼야 합니다

DART(opendart.fss.or.kr)는 **해외 IP 대역의 접속을 차단**합니다
(2026-07 실측: Cloudflare Workers 경유 시 연결 자체가 522 타임아웃).
따라서 해외 엣지에서 도는 Cloudflare Workers는 사용할 수 없고,
**서울 리전(icn1)을 지원하는 Vercel**을 권장합니다.

## 권장: Vercel 배포 (무료 · 서울 리전 · 도구 페이지까지 한 번에)

저장소 루트의 `vercel.json`이 함수 리전(icn1)과 정적 디렉터리(`docs/tool`)를
이미 지정해 두어, **배포 하나로 도구 페이지 + 릴레이가 같은 주소에서**
서빙됩니다(릴레이 주소 설정 불필요).

1. [vercel.com](https://vercel.com) 가입 (GitHub 계정으로, 무료·카드 불필요)
2. **Add New… → Project** → `dart-risk-mcp` 저장소 **Import**
3. Framework Preset: **Other** 그대로 → **Deploy**
4. 끝 — `https://<프로젝트명>.vercel.app` 이 도구 주소이자 릴레이 주소입니다.

동작 확인: `<주소>/api/company.json?crtfc_key=test` →
`{"status":"010", …}` JSON이 나오면 정상(미등록 키 오류 = 통과 성공).
master에 머지될 때마다 자동 재배포됩니다.

## 셀프호스트 (Python)

```bash
python scripts/dev_relay.py          # http://127.0.0.1:8787/
```

`docs/tool/` 정적 서빙 + `/api/` 프록시를 함께 제공합니다. 한국 내
네트워크에서 실행하면 즉시 작동합니다.

## 참고: Cloudflare Workers (`relay/worker.js`)

동일 계약의 Worker 구현을 기록용으로 유지합니다. 코드는 정상 동작하지만
Cloudflare 엣지가 해외 IP라 **DART 쪽에서 차단**되므로(522), DART가 정책을
바꾸지 않는 한 실사용은 불가합니다.
