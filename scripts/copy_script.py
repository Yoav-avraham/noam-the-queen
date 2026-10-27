import json
import os
import shutil
import subprocess
import argparse
from datetime import datetime, timezone
from pathlib import Path


def load_ignore_patterns(ignore_file_path: str) -> set:
    ignore_path = Path(ignore_file_path)
    if not ignore_path.exists():
        return set()

    patterns = set()
    with open(ignore_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                patterns.add(line)

    return patterns


def get_git_commit_info(cwd: Path) -> dict:
    fmt = "%H%x1f%an%x1f%ae%x1f%cI%x1f%s%x1f%B"
    try:
        out = subprocess.run(
            ["git", "log", "-1", f"--format={fmt}"],
            cwd=cwd, capture_output=True, text=True, check=True, encoding="utf-8",
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}

    sha, author, email, date, subject, body = out.split("\x1f", 5)
    return {
        "sha": sha,
        "short_sha": sha[:7],
        "author_name": author,
        "author_email": email,
        "commit_date": date,
        "subject": subject,
        "message": body.strip(),
    }


def build_commit_metadata(src_path: Path) -> dict:
    env = os.environ
    git_info = get_git_commit_info(src_path)

    head_sha = None
    event_path = env.get("GITHUB_EVENT_PATH")
    if event_path and Path(event_path).exists():
        try:
            event = json.loads(Path(event_path).read_text(encoding="utf-8"))
            head_sha = event.get("pull_request", {}).get("head", {}).get("sha")
        except (json.JSONDecodeError, OSError):
            pass

    sha = env.get("GITHUB_SHA") or git_info.get("sha")
    repo = env.get("GITHUB_REPOSITORY")
    server = env.get("GITHUB_SERVER_URL", "https://github.com")
    run_id = env.get("GITHUB_RUN_ID")

    return {
        "commit": {
            **git_info,
            "sha": sha,
            "short_sha": sha[:7] if sha else None,
            "pr_head_sha": head_sha,
            "url": f"{server}/{repo}/commit/{sha}" if repo and sha else None,
        },
        "ref": {
            "ref": env.get("GITHUB_REF"),
            "ref_name": env.get("GITHUB_REF_NAME"),
            "ref_type": env.get("GITHUB_REF_TYPE"),
        },
        "repository": repo,
        "actor": env.get("GITHUB_ACTOR"),
        "event_name": env.get("GITHUB_EVENT_NAME"),
        "workflow": env.get("GITHUB_WORKFLOW"),
        "run": {
            "id": run_id,
            "number": env.get("GITHUB_RUN_NUMBER"),
            "attempt": env.get("GITHUB_RUN_ATTEMPT"),
            "url": f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else None,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def write_metadata_file(dst: str, src_path: Path, filename: str):
    metadata = build_commit_metadata(src_path)
    out_path = Path(dst) / filename
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    print(f"Wrote commit metadata to {out_path}")


def copy_folder_with_txt_ignore(src: str, dst: str, ignore_file_path: str,
                                metadata_filename: str = "commit_metadata.json"):
    excluded = load_ignore_patterns(ignore_file_path)
    src_path = Path(src).resolve()

    def ignore_func(dir_path, contents):
        current_dir = Path(dir_path).resolve()
        ignored_names = set()

        for name in contents:
            item_path = current_dir / name
            try:
                rel_path = item_path.relative_to(src_path).as_posix()
            except ValueError:
                continue

            if name in excluded or rel_path in excluded or any(Path(rel_path).match(p) for p in excluded):
                ignored_names.add(name)

        return ignored_names

    shutil.copytree(
        src,
        dst,
        ignore=ignore_func,
        dirs_exist_ok=True
    )

    if metadata_filename:
        write_metadata_file(dst, src_path, metadata_filename)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("src", type=str)
    parser.add_argument("dst", type=str)
    parser.add_argument("ignore", type=str)
    parser.add_argument("--metadata-file", type=str, default="commit_metadata.json")

    args = parser.parse_args()
    copy_folder_with_txt_ignore(args.src, args.dst, args.ignore, args.metadata_file)
