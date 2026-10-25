import subprocess
import os
import shutil


def get_changes_since(commit="HEAD~1", repo_path="."):
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


def copy_changed_files(
    commit="HEAD~1",
    repo_path=".",
    output_dir="compressed",
    files_dir_name="files",
    clean=True,
):
    changed, _ = get_changes_since(commit, repo_path=repo_path)

    output_dir = os.path.abspath(output_dir)
    files_dir = os.path.join(output_dir, files_dir_name)

    # מנקה רק את תיקיית files, כך שדברים אחרים ב-compressed לא יימחקו
    if clean and os.path.exists(files_dir):
        shutil.rmtree(files_dir)
    os.makedirs(files_dir, exist_ok=True)

    copied = []
    for path in changed:
        src = os.path.join(repo_path, path)
        if not os.path.isfile(src):
            continue  # מדלג על דברים שאינם קבצים רגילים

        dst = os.path.join(files_dir, path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(path)

    return output_dir, copied

def main():
    print(output_dir, copied = copy_changed_files())
    
    
if __name__ == "__main__":
    main()
    