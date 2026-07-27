-- SE(스페셜 에디션) Supabase 초기 설정 — **이 파일 하나만** SQL Editor에 붙여넣고 실행하세요.
--
-- 전부 멱등(if not exists)이라 여러 번 실행해도 안전합니다.
-- 개별 파일(se_server/schema.sql, se_server/jobs/schema.sql,
-- se_server/jobs/migrations/001_owner.sql)의 내용을 합친 것입니다.
--
-- 실행 후 Storage 버킷 생성은 `python scripts/se_setup.py`가 대신 해줍니다.

-- ── 1) 캐시 (원문 ZIP 메타 + 구조화 API 응답) ──
-- 출처: se_server/schema.sql

-- SE 캐시 테이블. Supabase SQL 에디터에서 1회 실행한다.
-- 원문 ZIP은 Storage 버킷(기본 이름 se-cache)에 저장하므로 여기 없다.

create table if not exists se_cache (
  key        text primary key,
  value      jsonb not null,
  expires_at timestamptz
);

-- 만료 행 정리를 위한 인덱스
create index if not exists se_cache_expires_at_idx
  on se_cache (expires_at)
  where expires_at is not null;

-- service_role만 접근한다. 브라우저는 이 테이블을 직접 읽지 않는다.
alter table se_cache enable row level security;

-- ── 2) 작업 상태 ──
-- 출처: se_server/jobs/schema.sql

-- SE 작업 테이블. Supabase SQL 에디터에서 1회 실행한다.
-- state는 Job.to_dict() 전체를 담는다. DART API 키는 여기 들어가지 않는다.

create table if not exists se_jobs (
  job_id     text primary key,
  state      jsonb not null,
  status     text not null default 'running',
  -- 소유자. 신규 설치가 이 파일만 실행해도 컬럼이 있어야 한다 — 없으면
  -- supabase_store.save가 payload에 user_id를 넣어 PostgREST 400이 나고
  -- 작업 생성이 매번 500이 된다. 기존 인스턴스는 migrations/001_owner.sql이
  -- 담당하며, create table if not exists라 이 파일 재실행은 무해하다.
  user_id    text,
  updated_at timestamptz not null default now()
);

create index if not exists se_jobs_status_idx on se_jobs (status);
create index if not exists se_jobs_user_id_idx on se_jobs (user_id);

-- service_role만 접근한다. 브라우저는 이 테이블을 직접 읽지 않는다.
alter table se_jobs enable row level security;

-- ── 3) 소유자 마이그레이션 (기존 인스턴스용 — 신규 설치면 2)에 이미 포함) ──
-- 출처: se_server/jobs/migrations/001_owner.sql

-- se_jobs에 소유자 컬럼 추가. Supabase SQL 에디터에서 1회 실행한다.
-- SE-2가 만든 기존 레코드는 user_id가 NULL이 되며, 소유자 필터가 걸린
-- 조회에서는 잡히지 않는다(의도된 동작 — 소유자를 알 수 없는 작업이다).

alter table se_jobs add column if not exists user_id text;

create index if not exists se_jobs_user_id_idx on se_jobs (user_id);

