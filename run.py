"""Local preview: keep the web app and official collection worker running together."""
import subprocess
import sys
from pathlib import Path

if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    processes = [subprocess.Popen([sys.executable, '-m', 'sakura.collect', '--watch'], cwd=root),
                 subprocess.Popen([sys.executable, '-m', 'sakura.weather', '--watch'], cwd=root),
                 subprocess.Popen([sys.executable, 'app.py'], cwd=root)]
    print('季見本機預覽：http://127.0.0.1:5001 · 官方與氣象 worker 已啟動', flush=True)
    try:
        while True:
            for process in processes:
                code = process.poll()
                if code is not None:
                    raise SystemExit(code or 1)
            try:
                processes[-1].wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
