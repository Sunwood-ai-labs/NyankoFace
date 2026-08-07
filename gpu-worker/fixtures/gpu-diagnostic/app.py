from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
import json
import os
import subprocess


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,driver_version",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        rows = [line.strip() for line in query.stdout.splitlines() if line.strip()]
        assigned = os.getenv("CUDA_VISIBLE_DEVICES", "all")
        if assigned != "all":
            assigned_ids = {value.strip() for value in assigned.split(",")}
            rows = [row for row in rows if row.split(",", 1)[0].strip() in assigned_ids]
        payload = {
            "status": "ok",
            "runtime": "nyankoface-remote-gpu",
            "assigned_gpu_ids": assigned,
            "gpus": rows,
        }
        if self.path.rstrip("/") == "/api":
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            content_type = "application/json; charset=utf-8"
        else:
            cards = "".join(
                f"<li><span>GPU {index}</span><strong>{escape(gpu)}</strong></li>"
                for index, gpu in enumerate(payload["gpus"], start=1)
            )
            body = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>NyankoFace GPU Diagnostic</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, system-ui, sans-serif; }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; min-height: 100vh; display: grid; place-items: center;
      color: #e8fbff; background:
        radial-gradient(circle at 20% 0%, #143e4a 0, transparent 42%),
        linear-gradient(145deg, #050811, #0a1224 65%, #11152c);
    }}
    main {{ width: min(720px, calc(100% - 32px)); padding: 48px 0; }}
    .eyebrow {{ color: #59e1ed; font: 700 12px ui-monospace, monospace;
      letter-spacing: .18em; text-transform: uppercase; }}
    h1 {{ margin: 12px 0 8px; font-size: clamp(32px, 7vw, 56px); }}
    p {{ margin: 0 0 30px; color: #9db7c6; }}
    ul {{ display: grid; gap: 14px; padding: 0; list-style: none; }}
    li {{
      display: grid; gap: 8px; padding: 20px; border: 1px solid #285c70;
      border-radius: 16px; background: rgb(10 24 42 / .72);
      box-shadow: inset 0 1px rgb(255 255 255 / .04);
    }}
    li span {{ color: #54dce8; font: 700 11px ui-monospace, monospace;
      letter-spacing: .14em; }}
    li strong {{ font-size: 17px; line-height: 1.5; }}
    footer {{ margin-top: 28px; color: #638294; font-size: 12px; }}
  </style>
</head>
<body>
  <main>
    <div class="eyebrow">Remote worker verified</div>
    <h1>GPU Diagnostic</h1>
    <p>このSpaceはローカルGPUワーカー上のDockerコンテナで動作しています。</p>
    <ul>{cards}</ul>
    <footer>runtime: nyankoface-remote-gpu</footer>
  </main>
</body>
</html>""".encode("utf-8")
            content_type = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        return


ThreadingHTTPServer(("0.0.0.0", 7860), Handler).serve_forever()
