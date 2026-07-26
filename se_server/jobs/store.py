"""작업 저장소 인터페이스와 인메모리 구현."""
from __future__ import annotations

import secrets
from typing import Protocol

from se_server.jobs.model import Job


class JobStore(Protocol):
    """작업 상태를 보관하는 저장소가 제공해야 하는 최소 인터페이스."""

    def save(self, job: Job) -> None:
        """작업을 저장한다."""
        ...

    def load(self, job_id: str) -> Job | None:
        """작업 ID로 작업을 조회한다. 없으면 None."""
        ...


def new_job_id() -> str:
    """URL에 그대로 넣을 수 있는 작업 ID.

    secrets.token_urlsafe() 사용으로 충돌 없음을 보장.
    """
    return secrets.token_urlsafe(12)


class MemoryJobStore:
    """프로세스 메모리 저장소.

    개발·테스트 전용. 서버 재시작하면 날아가고, Vercel 무상태 함수는
    다음 요청마다 새 프로세스라 운영에서는 쓸 수 없다.

    저장·조회 모두 dict를 거쳐 복사본을 만든다. 실제 저장소(Postgres)는
    항상 새 객체를 돌려주므로, 참조를 공유하면 테스트가 실서비스와 다르게
    동작해 재개 버그를 놓치게 된다.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}

    def save(self, job: Job) -> None:
        """작업을 메모리에 저장한다."""
        self._jobs[job.job_id] = job.to_dict()

    def load(self, job_id: str) -> Job | None:
        """작업 ID로 작업을 조회한다. 없으면 None."""
        data = self._jobs.get(job_id)
        if data is None:
            return None
        return Job.from_dict(data)
