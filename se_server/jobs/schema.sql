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
