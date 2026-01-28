import os
import subprocess
import sys
from pathlib import Path

INPUT = r"C:\Users\user\Documents\White list\kommersant_20251210.csv"
OUTPUT = r"result.csv" 
LOG = Path(r"C:\Users\user\Documents\White list\validator_log.txt")

cmd = [
    sys.executable,
    "main.py",
    "validate",
    "--input", INPUT,
    "--output", OUTPUT
]    
    
p = subprocess.run(
    cmd,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    env={**dict(os.environ), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
)

text = (p.stdout or "") + (p.stderr or "")
LOG.write_text(text, encoding="utf-8-sig")

print(f"Лог сохранен в: {LOG}")
print(f"Код завершения: {p.returncode}")
