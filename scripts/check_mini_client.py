"""Run the native client controller/static checks without network access."""
from pathlib import Path
import shutil
import subprocess


def main():
    node = shutil.which('node')
    if not node:
        raise RuntimeError('Node.js is required for mini-program client checks')
    root = Path(__file__).resolve().parents[1]
    subprocess.run([node, str(root / 'scripts' / 'check_mini_client.cjs')], cwd=root, check=True, timeout=45)


if __name__ == '__main__':
    main()
