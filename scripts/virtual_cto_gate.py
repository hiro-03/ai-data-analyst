#!/usr/bin/env python3
"""
Virtual CTO 機械ゲート（.cursorrules 第 5 節の「再現性のある強制」をローカル・CI で補う）。

- --fast: pre-commit 用。pytest + mypy（リポジトリの pytest.ini に従う）。
- --github-summary: CI 用。$GITHUB_STEP_SUMMARY に手動チェックリストと実行コマンドを追記する。

手動レビュー項目（IAM・Secrets 整合など）は自動判定が難しいため、
PR テンプレートと本スクリプトのサマリーで「見える化」する。
"""
from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
from pathlib import Path

# Windows コンソール（cp932）で mypy の Unicode 出力が落ちないようにする
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )

# リポジトリルート（scripts/ の親）
ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], label: str) -> tuple[bool, str]:
    """コマンドを実行し、(成功, 表示用1行) を返す。"""
    try:
        r = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=600,
        )
        ok = r.returncode == 0
        tail = (r.stderr or r.stdout or "").strip().splitlines()
        detail = tail[-3:] if tail else []
        extra = "; ".join(detail) if detail else ("OK" if ok else "失敗")
        return ok, f"{label}: {'OK' if ok else 'NG'} — {extra[:500]}"
    except subprocess.TimeoutExpired:
        return False, f"{label}: NG — タイムアウト"
    except OSError as e:
        return False, f"{label}: NG — {e}"


def run_fast_gate() -> int:
    """pytest と mypy を実行（コミット前フック用）。"""
    lines: list[str] = []
    all_ok = True

    ok, msg = _run(
        [sys.executable, "-m", "pytest", "tests/"],
        "pytest",
    )
    lines.append(msg)
    all_ok = all_ok and ok

    ok, msg = _run(
        [
            sys.executable,
            "-m",
            "mypy",
            "layers/fishing_common/fishing_common/",
            "lambdas/",
            "--ignore-missing-imports",
            "--explicit-package-bases",
            "--no-error-summary",
        ],
        "mypy",
    )
    lines.append(msg)
    all_ok = all_ok and ok

    print("=== Virtual CTO 機械ゲート（--fast）===")
    for line in lines:
        print(line)
    if not all_ok:
        print(
            "\n修正するか、`git commit --no-verify` でスキップ（非推奨）。",
            file=sys.stderr,
        )
        return 1
    print("\n本リポジトリの Virtual CTO 機械チェック（pytest + mypy）は通過しました。")
    return 0


def append_github_summary() -> int:
    """GitHub Actions の Job サマリーに手動チェックリストを書き込む。"""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        print("GITHUB_STEP_SUMMARY が未設定のためサマリーはスキップします。", file=sys.stderr)
        return 0

    body = """
## Virtual CTO チェックリスト（手動・ドキュメント）

以下は **人間 / エージェント** が PR・リリース前に確認する項目です（自動では完走しません）。

| # | 項目 |
|---|------|
| 1 | IAM ポリシーに不適切な `Resource: "*"` がないか（README の既知例外を踏まえる） |
| 2 | README と GitHub Secrets / `template.yaml` の変数名が一致しているか |
| 3 | Flutter（`FishingResult` 等）とバックエンド Pydantic スキーマが一致しているか |
| 4 | 新規・変更コードに日本語コメントが必要な箇所が足りているか |

- 詳細: `.cursorrules` セクション 5
- 機械チェック: 同一ジョブ内の `pytest` / `mypy` / `sam validate` / `sam build`

"""
    with open(path, "a", encoding="utf-8") as f:
        f.write(body)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Virtual CTO 機械ゲート")
    p.add_argument(
        "--fast",
        action="store_true",
        help="pytest + mypy のみ実行（pre-commit 向け）",
    )
    p.add_argument(
        "--github-summary",
        action="store_true",
        help="GitHub Actions のジョブサマリーに手動チェックリストを追記",
    )
    args = p.parse_args()

    if args.github_summary:
        return append_github_summary()
    if args.fast:
        return run_fast_gate()
    p.print_help()
    print("\n通常は --fast または --github-summary を指定してください。", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
