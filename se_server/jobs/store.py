"""작업 저장소 인터페이스와 인메모리 구현."""
from __future__ import annotations

import copy
import secrets
from typing import Protocol

from se_server.jobs.model import Job


class JobStore(Protocol):
    """작업 상태를 보관하는 저장소가 제공해야 하는 최소 인터페이스."""

    def save(self, job: Job) -> None:
        """작업을 저장한다."""
        ...

    def load(self, job_id: str, user_id: str = "") -> Job | None:
        """작업 ID로 작업을 조회한다. 없으면 None.

        user_id가 주어지면 소유자가 다를 때도 None을 돌려준다.
        """
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

    **깊은 복사가 필요한 이유:** `WorkItem.from_dict`는 params·result를
    참조로 그대로 대입한다(얕은 복사). 저장소 내부 dict를 그대로
    `Job.from_dict`에 넘기면, `load()`가 돌려준 객체의 `item.params`나
    `item.result`를 제자리에서(in-place) 고치는 순간 — `save()`를 호출하기도
    전에 — 저장소 내부 dict가 함께 오염된다. Vercel 무상태 함수를 여러 번
    호출하며 `WorkItem.result`에 중간 결과를 채워 넣는 것이 이 계층의
    존재 이유이므로, 이 공유는 바로 이 모듈이 막으려던 재개 버그 그
    자체가 된다. `save()` 쪽은 `Job.to_dict()`가 `asdict()`를 거쳐 이미
    깊은 복사를 만들므로 문제없지만, `load()` 쪽은 `copy.deepcopy`로
    한 번 더 분리해야 한다.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}

    def save(self, job: Job) -> None:
        """작업을 메모리에 저장한다."""
        self._jobs[job.job_id] = job.to_dict()

    def load(self, job_id: str, user_id: str = "") -> Job | None:
        """작업 ID로 작업을 조회한다. 없으면 None.

        내부 dict를 깊은 복사해 넘긴다 — 그렇지 않으면 돌려준 Job의 중첩
        params·result가 저장소 내부 dict와 같은 객체가 된다.
        """
        data = self._jobs.get(job_id)
        if data is None:
            return None
        job = Job.from_dict(copy.deepcopy(data))
        # 소유자 불일치는 "없음"과 동일하게 취급한다. 404와 403을 구분하면
        # 남의 job_id가 존재하는지를 알려주게 된다.
        if user_id and job.user_id != user_id:
            return None
        return job
