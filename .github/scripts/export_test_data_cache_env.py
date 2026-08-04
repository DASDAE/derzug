"""Export DASCore test-data cache metadata for GitHub Actions."""

from __future__ import annotations

import os
from pathlib import Path

from dascore.utils.downloader import get_test_data_cache_info


def main() -> None:
    """Append the cache path and key to the job's GITHUB_ENV file."""
    info = get_test_data_cache_info()
    key = info.get_key(
        runner_os=os.environ["RUNNER_OS"],
        cache_number=os.environ["INPUT_CACHE_NUMBER"],
    )
    # Written to the file rather than echoed, so the step works unchanged under
    # both bash and pwsh (the Windows runners use the latter).
    lines = f"DATA_CACHE_PATH={info.cache_path}\nDATA_CACHE_KEY={key}\n"
    with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as fh:
        fh.write(lines)
    print(lines)  # noqa: T201


if __name__ == "__main__":
    main()
