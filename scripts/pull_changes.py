import subprocess


def get_changes_since(commit, repo_path="."):
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

    # קבצים שנמצאים תחת מעקב: נוספו, שונו, נמחקו או שונה שמם
    output = run("-c", "core.quotepath=false", "diff", "--name-status", commit)
    for line in output.splitlines():
        status, *paths = line.split("\t")
        code = status[0]  # R ו-C מגיעים עם אחוז דמיון, למשל R100

        if code == "D":
            deleted.add(paths[0])
        elif code == "R":
            # שינוי שם: הנתיב הישן נחשב נמחק, החדש נחשב נוצר
            deleted.add(paths[0])
            changed_or_created.add(paths[1])
        elif code == "C":
            changed_or_created.add(paths[1])
        else:  # A, M, T
            changed_or_created.add(paths[0])

    # קבצים חדשים שעדיין לא נוספו ל-git (untracked), בלי מה שמופיע ב-.gitignore
    untracked = run(
        "-c", "core.quotepath=false",
        "ls-files", "--others", "--exclude-standard",
    )
    changed_or_created.update(untracked.splitlines())

    return sorted(changed_or_created), sorted(deleted)


def main():
    
    changed, deleted = get_changes_since("3afe2ae", repo_path=".")

    print("שונו או נוצרו:", changed)
    print("נמחקו:", deleted)
    
    
if __name__ == "__main__":
    main()
    