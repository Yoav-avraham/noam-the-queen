import shutil
from pathlib import Path
import argparse

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

def copy_folder_with_txt_ignore(src: str, dst: str, ignore_file_path: str):
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("src", type=str)
    parser.add_argument("dst", type=str)
    parser.add_argument("ignore", type=str)
    
    args = parser.parse_args()
    copy_folder_with_txt_ignore(args.src, args.dst, args.ignore)
