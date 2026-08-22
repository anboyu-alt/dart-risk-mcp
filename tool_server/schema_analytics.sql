-- 공개 뷰어 접속 분석 스키마.
--
-- se_cache와 같은 원칙으로 RLS를 켜고 정책을 두지 않는다 — service_role
-- 키만 RLS를 우회하므로 서버 함수(api/track.py·api/stats.py) 외에는 읽을
-- 수도 쓸 수도 없다. anon 키로는 아무것도 안 보인다.
--
-- Supabase SQL 편집기에 1회 붙여넣어 실행한다. 재실행해도 안전하다.

create table if not exists viewer_events (
  id          bigserial primary key,
  ts          timestamptz not null default now(),
  event       text not null,          -- pageview | scan | compare | doc
  visitor_id  text,                   -- 쿠키 UUID (1년)
  ip          inet,
  country     text,
  region      text,
  city        text,
  ua          text,                   -- 원본
  browser     text,
  os          text,
  device      text,                   -- desktop | mobile | tablet | bot
  is_mobile   boolean,
  referrer    text,                   -- 쿼리스트링 제거된 origin+path
  corp_name   text,
  stock_code  text,
  path        text,
  screen      text,                   -- "1920x1080"
  lang        text
);

create index if not exists viewer_events_ts_idx on viewer_events (ts desc);
create index if not exists viewer_events_visitor_idx on viewer_events (visitor_id, ts desc);
create index if not exists viewer_events_corp_idx on viewer_events (corp_name);

alter table viewer_events enable row level security;

-- ── 집계 뷰 ────────────────────────────────────────────────────────────
-- PostgREST는 GROUP BY를 직접 지원하지 않는다. 행을 전부 끌어와 Python에서
-- 세면 데이터가 쌓일수록 응답이 무거워지므로, 집계를 DB에 맡긴다.
--
-- 날짜(day)를 그룹 키에 넣는 이유는 기간 필터(day=gte.YYYY-MM-DD)를 걸기
-- 위해서다. 그 대가로 회사별 순방문자는 날짜별 합이 되어 실제보다 커진다
-- (대시보드에서 "방문 연인원"으로 표기).

create or replace view v_corp_ranking as
select corp_name,
       stock_code,
       ts::date as day,
       count(*) as views,
       count(distinct visitor_id) as visitors
from viewer_events
where event = 'scan' and corp_name is not null
group by corp_name, stock_code, ts::date;

create or replace view v_traffic_daily as
select ts::date as day,
       count(*) filter (where event = 'pageview') as pageviews,
       count(*) filter (where event = 'scan') as scans,
       count(distinct visitor_id) as visitors
from viewer_events
group by ts::date;

create or replace view v_referrer_summary as
select coalesce(referrer, '(직접 유입)') as referrer,
       country,
       city,
       browser,
       os,
       device,
       ts::date as day,
       count(*) as hits
from viewer_events
group by referrer, country, city, browser, os, device, ts::date;

create or replace view v_visitor_sessions as
select visitor_id,
       min(ts) as first_seen,
       max(ts) as last_seen,
       count(*) as events,
       count(*) filter (where event = 'scan') as scans,
       -- host()로 넷마스크를 뗀다. ip::text는 inet을 CIDR(222.0.2.1/32)로 뱉어
       -- 방문자 표에 "/32"가 그대로 노출된다(프로덕션 실측, 2026-08-22).
       max(host(ip)) as last_ip,
       max(country) as country,
       max(city) as city,
       max(browser) as browser,
       max(os) as os,
       max(device) as device
from viewer_events
where visitor_id is not null
group by visitor_id;
