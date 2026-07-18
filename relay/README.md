# DART CORS 릴레이

라이브 리스크 도구(`docs/tool/`)가 브라우저에서 DART OpenAPI를 호출할 수 있게
하는 초소형 무상태 프록시입니다. DART가 CORS를 허용하지 않아 필요합니다.

**신뢰 경계**: 릴레이는 사용자의 API 키·요청·응답을 저장하거나 기록하지
않습니다. 허용된 2개 엔드포인트(`list.json`, `company.json`)의 GET 요청에
CORS 헤더만 붙여 통과시킵니다. 코드는 이 폴더에 전부 공개돼 있고,
아래 셀프호스트 방법으로 직접 띄워 쓸 수도 있습니다.

## 배포 (Cloudflare Workers, 무료)

1. [dash.cloudflare.com](https://dash.cloudflare.com) 가입 (무료, 카드 불필요)
2. **Workers & Pages → Create → Worker** → 이름 예: `dart-relay`
3. 편집기에 [`worker.js`](worker.js) 내용을 통째로 붙여넣고 **Deploy**
4. 발급된 URL(`https://dart-relay.<계정>.workers.dev`)을
   도구 페이지의 릴레이 주소 설정에 입력 — 끝.

무료 한도(일 10만 요청)는 이 용도에 충분합니다.

## 셀프호스트 (Python)

```bash
python scripts/dev_relay.py          # http://127.0.0.1:8787/
```

`docs/tool/` 정적 서빙 + `/api/` 프록시를 함께 제공하므로, 이 주소 하나로
도구 전체를 로컬에서 쓸 수 있습니다(릴레이 주소 설정 불필요 — 같은 출처).
