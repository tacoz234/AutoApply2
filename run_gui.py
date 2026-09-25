"""ApplyFlow Dashboard Launcher.

Starts the local web server and automatically opens the user's default browser.
"""

import socket
import sys
import time
import threading
import webbrowser
import uvicorn

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        if sys.stdout and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def find_free_port(start_port: int = 5000, max_attempts: int = 20) -> int:
    """Finds an available TCP port starting from start_port."""
    for p in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start_port


def open_browser_delayed(url: str, delay: float = 1.2):
    """Opens browser after server has started."""
    time.sleep(delay)
    try:
        webbrowser.open(url)
    except Exception:
        pass


def launch(port: int = 5000):
    free_port = find_free_port(port)
    url = f"http://127.0.0.1:{free_port}/"

    print("\n" + "=" * 60)
    print("  >> APPLYFLOW DASHBOARD")
    print(f"  Local Web GUI running at: {url}")
    print("=" * 60 + "\n")

    threading.Thread(target=open_browser_delayed, args=(url,), daemon=True).start()

    uvicorn.run(
        "src.gui_server:app",
        host="127.0.0.1",
        port=free_port,
        log_level="warning",
    )


if __name__ == "__main__":
    launch()
