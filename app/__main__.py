"""Run the app: ``python -m app [--host 127.0.0.1] [--port 8000]``."""
import argparse

import uvicorn


def main() -> None:
    ap = argparse.ArgumentParser(description="fit-git activity analytics server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true")
    args = ap.parse_args()
    uvicorn.run("app.main:create_app", factory=True, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
