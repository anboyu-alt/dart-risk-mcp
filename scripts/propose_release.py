#!/usr/bin/env python3
"""배포가 뒤처졌는지 보고 **릴리스를 제안**한다(배포하지 않는다).

## 왜 필요한가

`chore(release)` 커밋으로 버전을 올려도 **그것만으로는 배포되지 않는다** —
PyPI(`publish-pypi.yml`)와 Desktop 확장(`build-mcpb.yml`)의 유일한 방아쇠는
**GitHub Release 게시**다. 2026-08-31 실측: master가 `1.21.20`인데 PyPI는
`1.12.0`(2026-08-16)이었고, 그 사이 **222개 변경 · 62개 버전**이 사용자에게
가지 않고 있었다. 워크플로우가 실패한 게 아니라 **호출된 적이 없었다**
(실행 이력 전부 success).

## 무엇을 하지 않나

**자동으로 배포하지 않는다.** PyPI 업로드는 되돌릴 수 없고(같은 버전 번호를
다시 못 쓴다), 무엇을 언제 내보낼지는 사람이 정할 일이다. 이 스크립트는
사실을 모아 이슈로 **제안**만 하고, 판단은 제작자가 한다.

## 언제 제안하나

제작자 요청: *"아주 작은 수정까지 다 릴리스 할 필요는 없으니"*. 그래서
버전이 하나 앞섰다는 것만으로는 제안하지 않는다. 아래 중 하나면 제안한다.

- 새 기능(`feat`)이 있다
- 도구 목록이 바뀌었다(추가·제거) — 사용자가 쓰는 표면이 달라졌다
- 미배포 버전이 `_MANY_VERSIONS`개 이상 쌓였다

⚠ `_MANY_VERSIONS`·`_STALE_DAYS`는 **과거 이력에서 유도한 값이 아니다**.
이 레포의 실제 이력은 v1.12.0까지 거의 **1:1 배포**(간격 중앙값 1)였는데,
제작자가 그 관례를 바꾸겠다고 했으므로 이력은 근거가 되지 못한다. 이번
누락이 15일·62버전이었다는 사실만 참고해 **넉넉히** 잡은 출발값이고,
소음이 많거나 적으면 조정할 자리다. 이 값은 **제안 여부만** 정할 뿐
배포를 일으키지 않으므로 틀려도 손해가 작다.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request

# 제안 임계 — 위 독스트링의 경고 참고(이력 유도값 아님, 출발값)
_MANY_VERSIONS = 10
_STALE_DAYS = 21

_PYPI_SIMPLE = "https://pypi.org/simple/dart-risk-mcp/"


def _ver_key(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def fetch_pypi_latest(url: str = _PYPI_SIMPLE) -> str | None:
    """PyPI에 올라간 최신 버전. 실패하면 None(‘없다’가 아니라 ‘못 물어봤다’).

    ⚠ `/pypi/<pkg>/json`의 `info.version`은 **캐시가 뒤처진다** — 2026-08-31에
    1.21.20을 올린 직후에도 1.12.0을 돌려줬다. 설치가 실제로 읽는
    simple index를 본다.
    """
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.pypi.simple.v1+json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except Exception:  # noqa: BLE001 — 네트워크 실패는 판단 불가이지 ‘0건’이 아니다
        return None
    vs = [v for v in data.get("versions", []) if re.fullmatch(r"[\d.]+", v)]
    return max(vs, key=_ver_key) if vs else None


def repo_version(path: str = "dart_risk_mcp/__init__.py") -> str:
    m = re.search(r'__version__ = "([\d.]+)"', open(path, encoding="utf-8").read())
    if not m:
        raise SystemExit(f"{path}에서 __version__을 찾지 못했다")
    return m.group(1)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()


def gather(pypi_v: str | None) -> dict:
    """마지막 배포 이후 무엇이 쌓였는지 사실만 모은다."""
    base = f"v{pypi_v}" if pypi_v and _git("tag", "-l", f"v{pypi_v}") else ""
    rng = f"{base}..HEAD" if base else "HEAD"
    log = _git("log", "--no-merges", "--format=%s", rng).splitlines() if base else []
    subjects = [s for s in log if not s.startswith("chore(release)")]
    kinds: dict[str, int] = {}
    for s in subjects:
        m = re.match(r"([a-z]+)(\(.*?\))?:", s)
        kinds[m.group(1) if m else "기타"] = kinds.get(m.group(1) if m else "기타", 0) + 1
    days = 0
    if base:
        d = _git("log", "-1", "--format=%cd", "--date=format:%s", base)
        now = _git("log", "-1", "--format=%cd", "--date=format:%s", "HEAD")
        if d.isdigit() and now.isdigit():
            days = (int(now) - int(d)) // 86400
    releases = len([s for s in log if s.startswith("chore(release)")])
    return {"base": base, "subjects": subjects, "kinds": kinds,
            "days": days, "n_versions": releases,
            "feats": [s for s in subjects if s.startswith("feat")]}


def decide(repo_v: str, pypi_v: str | None, facts: dict) -> tuple[bool, str]:
    """제안할지와 그 이유. 순수 함수 — 네트워크·파일 접근 없음."""
    if pypi_v is None:
        return False, "PyPI에 물어보지 못했다 — 배포 상태를 알 수 없으므로 제안하지 않는다"
    if _ver_key(repo_v) <= _ver_key(pypi_v):
        return False, f"배포가 최신이다 (PyPI {pypi_v} ≥ master {repo_v})"
    why = []
    if facts["feats"]:
        why.append(f"새 기능 {len(facts['feats'])}건")
    if facts.get("tool_delta"):
        why.append(f"도구 목록 변경({facts['tool_delta']})")
    if facts["n_versions"] >= _MANY_VERSIONS:
        why.append(f"미배포 버전 {facts['n_versions']}개")
    if facts["days"] >= _STALE_DAYS and facts["subjects"]:
        why.append(f"마지막 배포 후 {facts['days']}일")
    if not why:
        return False, (f"앞서 있지만 작은 변경뿐이다 "
                       f"(미배포 {facts['n_versions']}개 · 기능 0건) — 제안하지 않는다")
    return True, " · ".join(why)


def body(repo_v: str, pypi_v: str, facts: dict, why: str) -> str:
    kinds = " · ".join(f"{k} {v}" for k, v in
                       sorted(facts["kinds"].items(), key=lambda x: -x[1]))
    lines = [
        f"master는 **{repo_v}**인데 PyPI는 **{pypi_v}**입니다.",
        "",
        f"- 제안 사유: {why}",
        f"- 미배포 버전 {facts['n_versions']}개 · 변경 {len(facts['subjects'])}건"
        + (f" · 마지막 배포 후 {facts['days']}일" if facts["days"] else ""),
        f"- 유형: {kinds}" if kinds else "",
        "",
        "`chore(release)` 커밋만으로는 배포되지 않습니다 — PyPI와 .mcpb 번들의",
        "방아쇠는 **GitHub Release 게시**입니다.",
        "",
    ]
    if facts["feats"]:
        lines += ["<details><summary>새 기능</summary>", ""]
        lines += [f"- {s}" for s in facts["feats"][:20]]
        lines += ["", "</details>", ""]
    lines += [
        "내보낼 준비가 되면:",
        "",
        "```bash",
        f"git tag -a v{repo_v} origin/master -m v{repo_v} && git push origin v{repo_v}",
        "```",
        "",
        f"그다음 태그로 Release를 게시하면 PyPI 업로드와 .mcpb 첨부가 자동 실행됩니다.",
        "지금 낼 만하지 않으면 이 이슈를 닫으세요 — 다음 점검 때 다시 제안합니다.",
    ]
    return "\n".join(l for l in lines if l is not None)


def main() -> int:
    ap = argparse.ArgumentParser(description="릴리스 제안 (배포하지 않음)")
    ap.add_argument("--pypi-version", default="",
                    help="테스트용 고정값 — 미지정 시 PyPI에 조회")
    ap.add_argument("--print-body", action="store_true")
    args = ap.parse_args()

    repo_v = repo_version()
    pypi_v = args.pypi_version or fetch_pypi_latest()
    facts = gather(pypi_v)
    ok, why = decide(repo_v, pypi_v, facts)

    print(f"master {repo_v} · PyPI {pypi_v or '(조회 실패)'}")
    print(f"제안: {'예' if ok else '아니오'} — {why}")
    if ok and args.print_body:
        print("---BODY---")
        print(body(repo_v, pypi_v or "?", facts, why))
    # GitHub Actions 출력
    import os
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"propose={'true' if ok else 'false'}\n")
            f.write(f"version={repo_v}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
