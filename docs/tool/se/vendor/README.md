# vendor/ — 반입 라이브러리

이 디렉토리의 파일은 저장소 자체 정적 검사(`tests/se/test_se_page_assets.py`의
`_sources()`) 대상이 아닙니다. `_sources()`는 `docs/tool/se/*.html`·`*.js`만
훑고 하위 디렉토리는 보지 않습니다 — 남의 코드를 우리 규칙(한국어 주석,
판정 어휘 금지 등)으로 검사할 이유가 없기 때문입니다. 대신 파일 존재·출처·
체크섬은 `TestVendoredChartLibrary`가 별도로 확인합니다.

## chart.umd.js

- **출처:** https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.js
- **버전:** 4.5.1
- **라이선스:** MIT — `(c) 2025 Chart.js Contributors`
- **크기:** 208,518 bytes (약 203.6 KB)

### 왜 CDN이 아니라 파일로 두는가

`/se`는 인가된 사람만 쓰는 서비스입니다. 페이지가 외부 CDN에서 스크립트를
불러오면 그 CDN 사업자가 접속 기록(요청자 IP, 리퍼러 — 즉 `/se` 자체의
존재와 접속 시각)을 갖게 됩니다. 파일을 저장소에 고정해 두면 이 기록이
아예 생기지 않고, 공급망 위험(CDN이 파일을 조용히 바꿔치기)도 사라지며,
CDN 장애와도 무관해집니다. 빌드 스텝은 여전히 없습니다 — 한 번 내려받아
커밋할 뿐입니다. `package.json`도 만들지 않습니다.

### 무결성 체크섬

CDN에서 `<script>`로 불러올 때는 `integrity="sha384-..."` 속성이 파일이
바뀌지 않았음을 브라우저가 검증하게 해줍니다. 파일을 반입하면 그 장치가
사라지므로, 대신 체크섬을 여기 기록해 두고 `tests/se/test_se_page_assets.py`의
`TestVendoredChartLibrary.test_library_file_matches_the_recorded_checksum`가
매 테스트 실행마다 강제합니다. 파일이 조용히 바뀌면(사고든 고의든) 테스트가
바로 깨지고, 의도적인 교체는 이 값을 함께 갱신해야 하므로 diff에 드러납니다.

```
sha384-hfkuqrKeWFmnTMWN31VWyoe8xgdTADD11kgxmdpx2uyE6j5Az5uZq6u6AKYYmAOw
```

리뷰어는 이 값을 npm/jsdelivr가 공표한 integrity 값과 대조해 진짜 배포본인지
확인할 수 있습니다. 검증 명령:

```bash
python -c "import hashlib,base64,pathlib; \
  d=pathlib.Path('docs/tool/se/vendor/chart.umd.js').read_bytes(); \
  print('sha384-'+base64.b64encode(hashlib.sha384(d).digest()).decode())"
```

### 갱신 방법

1. 새 버전 URL로 위 명령과 같은 방식으로 `chart.umd.js`를 내려받아 교체합니다
   (`curl`/`wget`은 이 저장소에서 차단돼 있으므로 Python 또는 Node로 받습니다).
2. 위 검증 명령으로 새 SHA-384 체크섬을 계산합니다.
3. 이 파일의 버전·크기·체크섬을 함께 갱신합니다.
4. `python -m pytest tests/se/test_se_page_assets.py -k Vendored -v`로 확인합니다.

### 포함된 것

UMD 단일 파일 빌드로 `LineController`·`BarController`·`CategoryScale`·
`LinearScale`·`Tooltip`·`Legend`를 포함합니다(등록형 API, `Chart.register`
불필요 — UMD 빌드는 auto-registerables를 기본 포함). 날짜는 문자열 라벨로
만들어 `category` 축을 쓰므로 `time` scale 어댑터(`chartjs-adapter-*`)는
필요하지 않습니다 — 두 번째 런타임 의존성을 늘리지 않습니다.
