"""작업 자료구조.

Vercel 함수는 실행 시간 상한이 있어 한 요청에서 분석을 끝낼 수 없다.
작업을 WorkItem 단위로 쪼개 상태를 외부에 남기고, 여러 번의 함수 호출에
나눠 실행한다.

항목 단위는 "DART 호출 1건"이다. 더 굵게 잡으면 한 항목이 시간 예산을
넘겨 영원히 끝나지 않는 항목이 생긴다.

설계: docs/superpowers/specs/2026-07-26-risk-viewer-se-design.md §6.1·§7.3
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

# 항목 상태
PENDING = "pending"
DONE = "done"
FAILED = "failed"


@dataclass
class WorkItem:
    """작업 하나. DART 호출 1건 또는 원문 1건에 대응한다.

    params에는 corp_code·연도·rcept_no 같은 조회 조건만 담는다.
    DART API 키는 절대 담지 않는다 — 작업 레코드는 공유 저장소에 남는다.
    """

    key: str
    stage: int
    kind: str
    params: dict = field(default_factory=dict)
    status: str = PENDING
    result: dict | None = None
    error: str = ""
    attempts: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "WorkItem":
        return cls(
            key=data["key"],
            stage=int(data["stage"]),
            kind=data["kind"],
            params=data.get("params") or {},
            status=data.get("status", PENDING),
            result=data.get("result"),
            error=data.get("error", ""),
            attempts=int(data.get("attempts", 0)),
        )


@dataclass
class Job:
    """회사 하나에 대한 분석 작업."""

    job_id: str
    company: str
    corp_code: str
    lookback_years: int
    items: list[WorkItem] = field(default_factory=list)
    status: str = "running"
    stage2_expanded: bool = False
    # 소유자. 빈 문자열이면 소유자 검사를 하지 않는다(CLI 경로).
    # job_id만으로 조회하게 두면 id가 곧 자격증명이 된다.
    user_id: str = ""

    def pending_items(self) -> list[WorkItem]:
        return [i for i in self.items if i.status == PENDING]

    def progress(self) -> tuple[int, int]:
        """(끝난 항목 수, 전체 항목 수). 실패도 '끝난' 것으로 센다."""
        finished = sum(1 for i in self.items if i.status in (DONE, FAILED))
        return finished, len(self.items)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "company": self.company,
            "corp_code": self.corp_code,
            "lookback_years": self.lookback_years,
            "items": [i.to_dict() for i in self.items],
            "status": self.status,
            "stage2_expanded": self.stage2_expanded,
            "user_id": self.user_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        return cls(
            job_id=data["job_id"],
            company=data["company"],
            corp_code=data["corp_code"],
            lookback_years=int(data["lookback_years"]),
            items=[WorkItem.from_dict(d) for d in data.get("items") or []],
            status=data.get("status", "running"),
            stage2_expanded=bool(data.get("stage2_expanded", False)),
            # SE-2가 만든 기존 레코드에는 이 키가 없다.
            user_id=data.get("user_id", ""),
        )
