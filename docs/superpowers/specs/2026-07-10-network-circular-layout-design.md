# 연결망 원형 레이아웃 + 줌 일원화 설계 (2026-07-10)

구현 대상: `scripts/network_template.html` 단일 파일 (빌드 스크립트·데이터 스키마 변경 없음).
이 문서는 상위 모델이 설계를 확정한 인수인계 명세다. 구현자는 아래 항목을
순서대로 적용하고, §6 검증 프로토콜을 통과시킨 뒤 PR을 올린다.

## 1. 배경 — 사용자 보고 4건

1. **비원형 실루엣**: 뭉치긴 하나 외곽선 모양을 정의하는 힘이 없어 들쭉날쭉.
2. **미아 노드**: 화면 구석으로 튕겨난 소형 군집이 그 자리에 동결. 축소해야만 보임.
3. **PC 무탄성**: 모바일은 주소창 접힘 resize가 alpha를 재가열해 계속 출렁이는데
   (우연의 산물), PC는 몇 초 뒤 식어서 정지. 사용자는 탄성 있는 쪽을 선호.
4. **모바일 더블탭 줌 충돌**: `touch-action:none`은 svg에만 있어, 고정 UI(범례·
   타임바·푸터) 위 더블탭이 **브라우저 네이티브 페이지 줌**을 발동 → 우리 줌
   버튼까지 화면 밖으로 밀려남. 인앱 줌(view.k)과 이중 기전.

## 2. 현재 물리엔진 스냅샷 (tick 함수)

- 반발력: 쌍별 `1500·k/d²`, **d²>90000(300px) 컷오프** — 이 컷오프가 미아 노드의
  상호작용 단절 원인. 성능상 유지한다.
- 스프링: 이상 길이 `46 + rOf(a) + rOf(b)`, 계수 0.04·k.
- 중심 인력: `(W/2−x)·0.0038·k` — **k(=alpha)에 곱해져 감쇠** → 튕겨난 노드가
  식으면서 동결되는 원인.
- 감쇠 0.86, alpha 감쇠 0.994, **alpha 바닥 0.02**.
- 초기 배치: 화면 중심 ± `0.34·min(W,H)` 정사각 랜덤.
- reduced-motion 분기: `for(500) tick()` 사전 수렴 후 정적 렌더 — §6 검증에 활용.
- 렌더 루프는 rAF로 상시 실행 중이므로 탄성 유지에 추가 비용 없음.

## 3. 변경 명세 (물리)

### 3-1. 소프트 원형 경계 — 핵심

월드 중심 `C=(W/2, H/2)`, 반경 `R`(§3-2). 매 tick, 각 노드에 대해:

```js
const dx = n.x - W/2, dy = n.y - H/2, r = Math.hypot(dx, dy);
if (r > R) {
  const f = (r - R) * 0.03;          // alpha(k)를 곱하지 않는다 — 상시 적용
  n.vx -= (dx / r) * f;  n.vy -= (dy / r) * f;
}
```

- **k를 곱하지 않는 것이 요점**: 식은 뒤에도 작동해 미아 노드가 구조적으로 불가능.
- 적용 위치: 중심 인력과 같은 노드 루프. `dragging` 노드는 기존 로직대로 적분
  스킵이므로 자연히 원 밖 드래그 허용 + 놓으면 복귀가 된다.
- 초과 거리 비례(선형)로 시작하고, 가장자리 링 밀집이 보이면 `f`를
  `(r-R)²·0.0008` 등 2차로 바꿔 완충 폭을 넓혀 본다.
- 기존 중심 인력(0.0038·k)은 유지 — 원 내부를 중심으로 모으는 역할.

### 3-2. 적응형 반경 — 노드 간격 기준

```js
const SPACING = 16;                              // 노드당 목표 간격 계수(튜닝 대상)
const R = Math.max(240, SPACING * Math.sqrt(nodes.length));
```

- 노드 수가 늘면 원이 √N으로 커져 **밀도(노드 간 거리)가 일정** 유지 —
  백필로 수천 노드가 되어도 같은 룩.
- `nodes.length`는 시뮬레이션 전체(숨김 exit_only 포함) 기준. 필터에 따라 R을
  다시 계산하지 않는다(단순성 우선).
- SPACING 초깃값 16, §6 스크린샷 보고 14~22 범위에서 튜닝.
- resize 시 재계산 불필요(월드 좌표 기준). 단 중심이 W/2,H/2라 resize 리스너가
  이미 alpha를 재가열하므로 새 중심으로 자연 이동한다. R은 상수로 두되
  W/2, H/2 참조는 tick 내 그대로 사용.

### 3-3. 원판 균등 초기 배치

정사각 랜덤 → 원판 균등(반경 √uniform):

```js
const t = Math.random() * 2 * Math.PI, rr = R * 0.9 * Math.sqrt(Math.random());
x: W/2 + Math.cos(t) * rr,  y: H/2 + Math.sin(t) * rr,
```

시작부터 원형이라 초기 폭발·튕김이 사라지고 수렴이 빨라진다.
(R 계산이 nodes 생성보다 앞서야 하므로 선언 순서 주의 — R은
`GRAPH.nodes.length`로 먼저 계산 가능.)

### 3-4. PC 상시 탄성

alpha 바닥을 `0.02 → 0.055`로 올린다 (`alpha *= 0.994; if (alpha < 0.055) ...`).
바닥에서도 반발·스프링이 미세하게 살아 은은히 숨 쉬는 느낌. 0.05~0.08 튜닝.
너무 크면 라벨이 흔들려 가독성 해침 — 정지 화면에서 라벨을 읽을 수 있어야 한다.
reduced-motion 분기의 `alpha = 0.02`는 그대로 두어 접근성 모드는 완전 정지 유지.

### 3-5. 초기 뷰·'전체' 버튼 원형 fit

```js
function fitView() {
  const k = Math.min(1, Math.min(W, H) / (2 * R * 1.12));   // 원 지름 + 12% 여백
  view.k = k;
  view.x = W/2 - W/2 * k;  view.y = H/2 - H/2 * k;          // 월드 중심을 화면 중심에
  applyView();
}
```

- 로드 직후 1회 호출, `z-fit`(전체 보기) 버튼을 `view={0,0,1}` 리셋 대신
  `fitView()` + alpha 재가열로 교체.
- 모바일 좁은 화면에서도 원 전체가 항상 들어온다.

## 4. 변경 명세 (줌 일원화)

### 4-1. 네이티브 더블탭 줌 전면 차단

- CSS: `html, body { touch-action: manipulation; }` 추가 (svg의 `none`은 유지).
  고정 UI 위 더블탭까지 차단하는 것이 목적.
- viewport 메타를 `content="width=device-width, initial-scale=1, maximum-scale=1,
  user-scalable=no"`로 교체 (Android 커버; iOS는 위 CSS가 커버).
- 그래프는 앱형 캔버스라 페이지 줌 차단이 접근성상 허용 범위 — 인앱 줌이 6배까지
  제공되고 상세 패널 텍스트는 OS 글자 크기를 따른다.

### 4-2. 인앱 더블탭/더블클릭 줌

- svg `dblclick` → `zoomAt(ev.clientX, ev.clientY, 1.6)` (데스크톱).
- 터치: pointerup에서 300ms·30px 내 연속 두 탭 감지 → 같은 `zoomAt` 호출.
  단일 탭의 기존 역할(노드 탭=상세, 빈 곳 탭=패널 닫기)과 충돌하지 않게
  두 번째 탭에서만 줌을 발동하고, 노드 위 더블탭이면 줌 대신 상세 유지.
- 기존 핀치(포인터 2개)·휠·버튼 줌 로직은 그대로 — 모두 단일 `zoomAt` 경유라
  기전이 하나로 통일된다.

## 5. 건드리지 말 것 (회귀 금지)

- 노드 드래그/팬/핀치 포인터 상태기계, 호버 하이라이트, 상세 패널, 타임
  스크러버, exit_only 필터·'이탈 있는 관계만' 토글, 테마 토글, 별칭 `⚑ 다른 이름`.
- CSP-safe 원칙: 외부 CDN·라이브러리 금지, 순수 JS 유지.
- 출력 HTML(실명 포함)은 public 레포에 커밋 금지 — 템플릿·스크립트만 커밋.

## 6. 검증 프로토콜 (검증된 명령)

실데이터는 비공개 저장소 `anboyu-alt/dart-risk-mcp-sightings`의 `sightings.json`을
로컬 임시 디렉터리에 클론해 쓴다(`$SP`는 세션 스크래치 경로 — 작업 세션에
이미 `$SP/sightings-priv/`로 클론돼 있으면 재사용).

```bash
# 1) JS 문법 검증 (템플릿에서 <script> 추출 → node --check)
python -c "
import re; html=open('scripts/network_template.html',encoding='utf-8').read()
open('/tmp/tpl.js','w').write('\n'.join(re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)))"
node --check /tmp/tpl.js

# 2) 실데이터 빌드
PYTHONPATH=. SIGHTINGS_PATH=$SP/sightings-priv/sightings.json \
  python scripts/build_network_html.py --out $SP/after.html

# 3) 수렴 레이아웃 스크린샷 — reduced-motion 분기(500틱 사전 수렴)를 이용한 결정적 캡처
CHROME=/opt/pw-browsers/chromium-1194/chrome-linux/chrome
$CHROME --headless --disable-gpu --no-sandbox --force-prefers-reduced-motion \
  --window-size=1990,712 --screenshot=$SP/after-pc.png --virtual-time-budget=8000 \
  "file://$SP/after.html"
$CHROME --headless --disable-gpu --no-sandbox --force-prefers-reduced-motion \
  --window-size=390,844 --screenshot=$SP/after-mobile.png --virtual-time-budget=8000 \
  "file://$SP/after.html"
```

스크린샷을 Read로 열어 판정. 비교 기준 이전 상태: `$SP/before.png`.

### 수용 기준

1. PC·모바일 모두 **외곽 실루엣이 원형** — 들쭉날쭉한 돌출·장축 없음.
2. **원 밖 노드 0개** — 캔버스 구석에 고립 노드 없음, 기본 뷰에서 전부 보임.
3. 기본 뷰에서 원 전체가 여백 포함 화면 안에 fit.
4. 라벨 가독 — 밀도가 과하면 SPACING↑, 원이 허전하면 SPACING↓ 재튜닝.
5. `node --check` 통과, 상세 패널·스크러버·필터 수동 확인(스크린샷상 UI 정상).
6. (탄성·더블탭은 정적 캡처로 확인 불가 — 코드 리뷰로 §3-4·§4 반영 확인,
   최종은 사용자 실기기 확인에 맡긴다.)

## 7. 작업 절차

1. 브랜치 `feat/network-circular-layout` (origin/master 기점).
2. §3→§4 순서로 구현, 각 단계 후 §6-1 문법 검증.
3. §6 스크린샷 튜닝 루프 (SPACING, 경계 계수, alpha 바닥).
4. before/after 스크린샷을 사용자에게 제시 → 승인 후 PR 생성 (머지는 사용자).
5. 커밋·PR 본문에 모델명 금지, 실명 데이터 금지 (스크린샷은 채팅으로만 공유,
   레포·PR에 첨부 금지 — 실명 라벨이 담긴다).
