import webbrowser

import uvicorn

from . import config

if __name__ == "__main__":
    url = f"http://{config.HOST}:{config.PORT}"
    print(f"Concall Player running at {url}  (Ctrl+C to stop)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    uvicorn.run("concall.server:app", host=config.HOST, port=config.PORT, log_level="warning")
