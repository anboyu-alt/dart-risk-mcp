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
