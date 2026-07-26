"""콘솔 출력 보조.

Windows 기본 콘솔은 cp949라 한국어 출력이 UnicodeEncodeError로 죽거나 깨진다
(SE-2 라이브 실측 중 실제로 재현됐다). PYTHONIOENCODING을 강제하는 대신
stdout/stderr를 utf-8로 재설정해 별도 환경변수 없이도 동작하게 한다.
"""
import sys


def use_utf8_stdout() -> None:
    """stdout·stderr를 utf-8로 재설정한다. 지원하지 않는 환경에서는 조용히 넘어간다."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                # 리다이렉트된 스트림 등에서 실패할 수 있다. 출력이 깨질 뿐
                # 기능에는 영향이 없으므로 진행한다.
                pass
