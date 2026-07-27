-- se_jobs에 소유자 컬럼 추가. Supabase SQL 에디터에서 1회 실행한다.
-- SE-2가 만든 기존 레코드는 user_id가 NULL이 되며, 소유자 필터가 걸린
-- 조회에서는 잡히지 않는다(의도된 동작 — 소유자를 알 수 없는 작업이다).

alter table se_jobs add column if not exists user_id text;

create index if not exists se_jobs_user_id_idx on se_jobs (user_id);
