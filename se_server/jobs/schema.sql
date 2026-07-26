-- SE 작업 테이블. Supabase SQL 에디터에서 1회 실행한다.
-- state는 Job.to_dict() 전체를 담는다. DART API 키는 여기 들어가지 않는다.

create table if not exists se_jobs (
  job_id     text primary key,
  state      jsonb not null,
  status     text not null default 'running',
  updated_at timestamptz not null default now()
);

create index if not exists se_jobs_status_idx on se_jobs (status);

-- service_role만 접근한다. 브라우저는 이 테이블을 직접 읽지 않는다.
alter table se_jobs enable row level security;
