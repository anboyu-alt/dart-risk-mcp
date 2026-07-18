# DART CORS 릴레이

라이브 리스크 도구(`docs/tool/`)가 브라우저에서 DART OpenAPI를 호출할 수 있게
하는 초소형 무상태 프록시입니다. DART가 CORS를 허용하지 않아 필요합니다.

**신뢰 경계**: 릴레이는 사용자의 API 키·요청·응답을 저장하거나 기록하지
않습니다. 허용된 2개 엔드포인트(`list.json`, `company.json`)의 GET 요청에
CORS 헤더만 붙여 통과시킵니다. 코드는 이 폴더에 전부 공개돼 있고,
아래 셀프호스트 방법으로 직접 띄워 쓸 수도 있습니다.

## 배포 (Cloudflare Workers, 무료)

> 2026-07 기준 대시보드 UI. Cloudflare가 화면을 자주 바꾸므로, 요지는
> "워커 하나 만들고 → 온라인 편집기에 worker.js를 붙여넣고 → 배포"입니다.

1. [dash.cloudflare.com](https://dash.cloudflare.com) 가입 (무료, 카드 불필요)
2. **Workers 및 Pages** 페이지 → 우상단 **애플리케이션 생성**
3. **Workers** 탭에서 **"Hello World" 시작** 선택 (Git 연동·템플릿 갤러리는
   불필요) → 이름 예: `dart-relay` → **배포**
4. 배포 완료 화면에서 **코드 편집**(Edit code) → 기존 코드를 전부 지우고
   [`worker.js`](worker.js) 내용을 통째로 붙여넣기 → 우상단 **배포**
5. 발급된 URL(`https://dart-relay.<하위도메인>.workers.dev`)을
   도구 페이지의 릴레이 주소 설정에 입력 — 끝.

동작 확인: 브라우저에서 `<발급 URL>/api/company.json?crtfc_key=test`를 열어
`{"status":"010", …}` JSON이 나오면 정상입니다(미등록 키 오류 = 통과 성공).

대안: 대시보드 구성이 다르면 [Workers Playground](https://workers.cloudflare.com/playground)에
`worker.js`를 붙여넣고 우상단 **Deploy**로 배포해도 동일합니다.

무료 한도(일 10만 요청)는 이 용도에 충분합니다.

## 셀프호스트 (Python)

```bash
python scripts/dev_relay.py          # http://127.0.0.1:8787/
```

`docs/tool/` 정적 서빙 + `/api/` 프록시를 함께 제공하므로, 이 주소 하나로
도구 전체를 로컬에서 쓸 수 있습니다(릴레이 주소 설정 불필요 — 같은 출처).
