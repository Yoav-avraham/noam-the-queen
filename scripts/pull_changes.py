import subprocess
import os
import shutil
import sys


def get_changes_since(commit="HEAD~1", repo_path="."):
    """Return two sorted lists: (changed_or_created, deleted)."""

    def run(*args):
        return subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=True,
            cwd=repo_path,
        ).stdout

    changed_or_created = set()
    deleted = set()

    # Tracked files: added, modified, deleted or renamed
    output = run("-c", "core.quotepath=false", "diff", "--name-status", commit)
    for line in output.splitlines():
        status, *paths = line.split("\t")
        code = status[0]  # R and C come with a similarity score, e.g. R100

        if code == "D":
            deleted.add(paths[0])
        elif code == "R":
            # Rename: the old path counts as deleted, the new one as created
            deleted.add(paths[0])
            changed_or_created.add(paths[1])
        elif code == "C":
            changed_or_created.add(paths[1])
        else:  # A, M, T
            changed_or_created.add(paths[0])

    # New files not yet added to git (untracked), excluding anything in .gitignore
    untracked = run(
        "-c", "core.quotepath=false",
        "ls-files", "--others", "--exclude-standard",
    )
    changed_or_created.update(untracked.splitlines())

    return sorted(changed_or_created), sorted(deleted)


def copy_changed_files(
    commit="HEAD~1",
    repo_path=".",
    output_dir="compressed",
    files_dir_name="files",
    clean=True,
):
    """Copy changed/created files into <output_dir>/<files_dir_name>,
    preserving the original folder structure."""
    changed, _ = get_changes_since(commit, repo_path=repo_path)

    output_dir = os.path.abspath(output_dir)
    files_dir = os.path.join(output_dir, files_dir_name)

    # Clean only the files folder, so anything else in compressed is preserved
    if clean and os.path.exists(files_dir):
        shutil.rmtree(files_dir)
    os.makedirs(files_dir, exist_ok=True)

    copied = []
    for path in changed:
        src = os.path.join(repo_path, path)
        if not os.path.isfile(src):
            continue  # Skip anything that is not a regular file

        dst = os.path.join(files_dir, path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(path)

    return output_dir, copied


def main():
    # On the runner the repo lives in GITHUB_WORKSPACE; locally use the current dir
    repo_path = os.environ.get("GITHUB_WORKSPACE", ".")

    # Create the folder on the runner, outside the repo, so it doesn't show up
    # as an untracked file in the list of changes
    runner_temp = os.environ.get("RUNNER_TEMP", os.path.dirname(os.path.abspath(repo_path)))
    output_dir = os.path.join(runner_temp, "compressed")

    try:
        output_dir, copied = copy_changed_files(
            repo_path=repo_path,
            output_dir=output_dir,
        )
    except subprocess.CalledProcessError as e:
        print(f"git failed: {e.stderr}", file=sys.stderr)
        sys.exit(1)

    print(f"Created folder: {output_dir}")
    print(f"Copied {len(copied)} files")

    # Pass the path to later steps in the pipeline
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"output_dir={output_dir}\n")


if __name__ == "__main__":
    main()
    