from __future__ import annotations

import hashlib
import hmac
import html
import os
import re
import secrets
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Runtime Environment Receipt")

DEFAULT_HEADLINE = "Waiting for runtime configuration"
DEFAULT_REGION = "not-configured"
DEFAULT_ACCENT = "#5eead4"
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def public_config() -> dict[str, str]:
    accent = os.getenv("DEMO_ACCENT", DEFAULT_ACCENT)
    if not HEX_COLOR.fullmatch(accent):
        accent = DEFAULT_ACCENT
    return {
        "headline": os.getenv("DEMO_HEADLINE", DEFAULT_HEADLINE),
        "region": os.getenv("DEMO_REGION", DEFAULT_REGION),
        "accent": accent,
    }


def secret_status() -> dict[str, str | bool]:
    token = os.getenv("DEMO_API_TOKEN", "")
    if not token:
        return {"configured": False, "fingerprint": "not configured"}
    fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
    return {"configured": True, "fingerprint": fingerprint}


def signed_receipt() -> dict[str, str | bool]:
    token = os.getenv("DEMO_API_TOKEN", "")
    now = datetime.now(timezone.utc).isoformat()
    nonce = secrets.token_hex(4)
    payload = f"{public_config()['region']}|{now}|{nonce}"
    signature = (
        hmac.new(token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if token
        else ""
    )
    return {
        "signed": bool(token),
        "issued_at": now,
        "nonce": nonce,
        "signature": signature,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/runtime")
def runtime() -> dict:
    return {"variables": public_config(), "secret": secret_status()}


@app.post("/api/receipt")
def receipt() -> dict[str, str | bool]:
    return signed_receipt()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    config = public_config()
    secret = secret_status()
    secret_label = "SIGNING KEY ONLINE" if secret["configured"] else "SIGNING KEY MISSING"
    secret_class = "online" if secret["configured"] else "offline"

    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#07110f">
  <title>Runtime Environment Receipt</title>
  <style>
    :root {{
      --ink: #eafbf6;
      --muted: #89aaa1;
      --line: #23463f;
      --panel: #0b1916;
      --accent: {config["accent"]};
      --paper: #07110f;
    }}
    * {{ box-sizing: border-box; }}
    html {{ color-scheme: dark; }}
    body {{
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      background:
        linear-gradient(rgba(94,234,212,.045) 1px, transparent 1px),
        linear-gradient(90deg, rgba(94,234,212,.045) 1px, transparent 1px),
        radial-gradient(circle at 78% 12%, color-mix(in srgb, var(--accent) 15%, transparent), transparent 30%),
        var(--paper);
      background-size: 28px 28px, 28px 28px, auto, auto;
      font-family: "Aptos Mono", "IBM Plex Mono", ui-monospace, monospace;
    }}
    main {{ width: min(1100px, calc(100% - 40px)); margin: 0 auto; padding: 40px 0 72px; }}
    .masthead {{
      display: flex; justify-content: space-between; gap: 24px; align-items: center;
      padding-bottom: 18px; border-bottom: 1px solid var(--line);
      color: var(--muted); font-size: 12px; letter-spacing: .16em; text-transform: uppercase;
    }}
    .live {{ display: inline-flex; align-items: center; gap: 9px; }}
    .live::before {{
      content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--accent);
      box-shadow: 0 0 18px var(--accent);
    }}
    .hero {{ display: grid; grid-template-columns: 1.35fr .65fr; gap: 42px; padding: 76px 0 58px; }}
    .kicker {{ color: var(--accent); font-size: 12px; letter-spacing: .22em; text-transform: uppercase; }}
    h1 {{
      max-width: 760px; margin: 18px 0 20px;
      font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
      font-size: clamp(50px, 7.4vw, 105px); font-weight: 500; line-height: .92; letter-spacing: -.055em;
    }}
    .lede {{ max-width: 650px; color: var(--muted); font: 17px/1.7 "Aptos", sans-serif; }}
    .seal {{
      align-self: end; aspect-ratio: 1; border: 1px solid var(--line); border-radius: 50%;
      display: grid; place-items: center; position: relative; color: var(--accent);
    }}
    .seal::before, .seal::after {{ content: ""; position: absolute; border: 1px solid var(--line); border-radius: 50%; }}
    .seal::before {{ inset: 12%; }} .seal::after {{ inset: 27%; }}
    .seal strong {{ font-size: clamp(34px, 5vw, 68px); font-weight: 400; }}
    .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); border: 1px solid var(--line); }}
    .datum {{ min-height: 156px; padding: 24px; border-right: 1px solid var(--line); background: color-mix(in srgb, var(--panel) 92%, transparent); }}
    .datum:last-child {{ border-right: 0; }}
    .label {{ display: block; color: var(--muted); font-size: 11px; letter-spacing: .18em; text-transform: uppercase; }}
    .value {{ display: block; margin-top: 34px; font-size: clamp(18px, 2.6vw, 30px); overflow-wrap: anywhere; }}
    .secret-panel {{
      margin-top: 24px; display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 28px;
      border: 1px solid var(--line); padding: 28px; background: var(--panel);
    }}
    .secret-state {{ display: flex; align-items: center; gap: 16px; }}
    .lock {{
      width: 52px; height: 52px; border: 1px solid var(--line); display: grid; place-items: center;
      color: var(--accent); font-size: 22px;
    }}
    .status {{ display: block; font-size: 16px; letter-spacing: .08em; }}
    .fingerprint {{ display: block; margin-top: 7px; color: var(--muted); font-size: 12px; }}
    .offline .status {{ color: #fda4af; }}
    button {{
      appearance: none; border: 1px solid var(--accent); background: var(--accent); color: #03120e;
      padding: 15px 20px; font: 700 12px/1 "Aptos Mono", monospace; letter-spacing: .1em;
      text-transform: uppercase; cursor: pointer; transition: transform .18s ease, box-shadow .18s ease;
    }}
    button:hover {{ transform: translateY(-2px); box-shadow: 0 8px 28px color-mix(in srgb, var(--accent) 28%, transparent); }}
    button:disabled {{ cursor: wait; opacity: .55; transform: none; }}
    .receipt {{
      margin-top: 24px; min-height: 108px; border-left: 3px solid var(--accent); padding: 18px 22px;
      background: rgba(2,9,8,.72); color: var(--muted); font-size: 12px; line-height: 1.8; overflow-wrap: anywhere;
    }}
    .receipt b {{ color: var(--ink); }}
    footer {{ display: flex; justify-content: space-between; gap: 20px; margin-top: 38px; color: var(--muted); font-size: 11px; }}
    @media (max-width: 760px) {{
      main {{ width: calc(100% - 28px); max-width: 620px; padding-top: 24px; }}
      .masthead {{ align-items: flex-start; flex-direction: column; gap: 10px; }}
      .hero {{ grid-template-columns: 1fr; padding: 52px 0 38px; }}
      h1 {{ font-size: clamp(42px, 14vw, 64px); }}
      .seal {{ width: 156px; justify-self: end; }}
      .grid {{ grid-template-columns: 1fr; }}
      .datum {{ min-height: 124px; border-right: 0; border-bottom: 1px solid var(--line); }}
      .datum:last-child {{ border-bottom: 0; }}
      .value {{ margin-top: 22px; }}
      .secret-panel {{ grid-template-columns: 1fr; }}
      button {{ width: 100%; }}
      footer {{ flex-direction: column; }}
    }}
  </style>
</head>
<body>
<main>
  <header class="masthead">
    <span>NyankoFace / CPU Space / runtime-only</span>
    <span class="live">Container online</span>
  </header>

  <section class="hero">
    <div>
      <span class="kicker">Environment proof № 01</span>
      <h1>{html.escape(config["headline"])}</h1>
      <p class="lede">NyankoFaceから渡されたVariableを表示し、暗号化Secretを使ってサーバー側で署名付きレシートを生成します。Secretの生値はブラウザへ返しません。</p>
    </div>
    <div class="seal" aria-hidden="true"><strong>ENV</strong></div>
  </section>

  <section class="grid" aria-label="Runtime variables">
    <div class="datum"><span class="label">Region / Variable</span><strong class="value">{html.escape(config["region"])}</strong></div>
    <div class="datum"><span class="label">Accent / Variable</span><strong class="value">{html.escape(config["accent"])}</strong></div>
    <div class="datum"><span class="label">Injection scope</span><strong class="value">Runtime only</strong></div>
  </section>

  <section class="secret-panel {secret_class}">
    <div class="secret-state">
      <div class="lock" aria-hidden="true">◆</div>
      <div>
        <strong class="status">{secret_label}</strong>
        <span class="fingerprint">SHA-256 fingerprint: {html.escape(str(secret["fingerprint"]))} · raw value hidden</span>
      </div>
    </div>
    <button id="sign" type="button" onclick="createReceipt()">Generate signed receipt</button>
  </section>

  <output class="receipt" id="receipt" aria-live="polite">
    <b>READY</b><br>Select “Generate signed receipt” to prove the runtime Secret is usable.
  </output>

  <footer>
    <span>No build args. No repository secrets. No client-side token.</span>
    <span>HMAC-SHA256 / {datetime.now(timezone.utc).strftime("%Y-%m-%d")}</span>
  </footer>
</main>
<script>
  async function createReceipt() {{
    const button = document.getElementById("sign");
    const output = document.getElementById("receipt");
    button.disabled = true;
    output.innerHTML = "<b>SIGNING…</b><br>Creating a receipt inside the Space container.";
    try {{
      const response = await fetch("api/receipt", {{ method: "POST" }});
      if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
      const data = await response.json();
      output.innerHTML = data.signed
        ? `<b>VERIFIED SIGNATURE</b><br>Issued: ${{data.issued_at}}<br>Nonce: ${{data.nonce}}<br>HMAC: ${{data.signature}}`
        : "<b>SECRET NOT CONFIGURED</b><br>Add DEMO_API_TOKEN as a Secret in NyankoFace, then restart this Space.";
    }} catch (error) {{
      output.innerHTML = `<b>REQUEST FAILED</b><br>${{error.message}}`;
    }} finally {{
      button.disabled = false;
    }}
  }}
</script>
</body>
</html>"""
