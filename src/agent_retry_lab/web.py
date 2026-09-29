"""Local-only HTTP interface used to record the retry demonstration."""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import PayloadConflictError, list_effects, run_operation


PAGE = r"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Retry pós-commit</title>
  <style>
    :root { color-scheme: dark; --ink:#080b10; --panel:#121823; --line:#293346; --paper:#f5f7fb; --muted:#98a5b8; --blue:#6687ff; --cyan:#66e5d4; --orange:#ff6b45; --green:#79e59b; }
    * { box-sizing: border-box; }
    body { margin:0; min-height:100vh; background:radial-gradient(circle at 15% 0%,#17223a 0,#080b10 37%); color:var(--paper); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    main { width:min(900px,100%); margin:auto; padding:44px 48px 54px; }
    .eyebrow { color:var(--cyan); font-size:20px; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }
    h1 { margin:14px 0 8px; max-width:760px; font-size:58px; line-height:.96; letter-spacing:-.045em; }
    .subtitle { margin:0 0 28px; color:var(--muted); font-size:23px; line-height:1.35; }
    .controls { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-bottom:20px; }
    button { min-height:64px; padding:12px 14px; border:1px solid var(--line); border-radius:14px; background:#171e2b; color:var(--paper); font-size:18px; font-weight:760; cursor:pointer; }
    button:hover,button:focus-visible { border-color:var(--blue); outline:none; }
    button[data-kind="naive"] { border-color:#763426; }
    button[data-kind="safe"] { border-color:#2f557f; }
    button[data-kind="conflict"] { border-color:#5c477f; }
    .summary { display:grid; grid-template-columns:1.2fr 1fr 1fr; gap:12px; margin-bottom:18px; }
    .metric,.panel { border:1px solid var(--line); border-radius:18px; background:rgba(18,24,35,.94); box-shadow:0 16px 50px rgba(0,0,0,.25); }
    .metric { padding:18px 20px; min-height:112px; }
    .metric span { display:block; color:var(--muted); font-size:16px; font-weight:720; text-transform:uppercase; letter-spacing:.06em; }
    .metric strong { display:block; margin-top:7px; font-size:34px; line-height:1; }
    #effectCount.danger { color:var(--orange); }
    #effectCount.safe { color:var(--green); }
    .grid { display:grid; grid-template-columns:1.05fr .95fr; gap:18px; }
    .panel { padding:22px; min-height:510px; }
    h2 { margin:0 0 18px; font-size:22px; }
    .timeline { display:flex; flex-direction:column; gap:11px; }
    .event { display:grid; grid-template-columns:42px 1fr auto; align-items:center; gap:12px; min-height:58px; padding:10px 12px; border:1px solid var(--line); border-radius:12px; background:#0c1119; opacity:0; translate:0 10px; transition:opacity .22s ease,translate .22s ease,border-color .22s ease; }
    .event.visible { opacity:1; translate:0 0; }
    .event .n { width:34px; height:34px; display:grid; place-items:center; border-radius:50%; background:#1b2535; color:var(--blue); font-weight:820; }
    .event strong { display:block; font-size:18px; }
    .event small { color:var(--muted); font-size:14px; }
    .event .tag { font-size:13px; font-weight:800; letter-spacing:.04em; text-transform:uppercase; }
    .event.danger { border-color:#703727; } .event.danger .tag { color:var(--orange); }
    .event.safe { border-color:#285448; } .event.safe .tag { color:var(--green); }
    .event.info .tag { color:var(--cyan); }
    table { width:100%; border-collapse:collapse; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:14px; }
    th { padding:0 8px 11px; color:var(--muted); text-align:left; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; font-size:13px; text-transform:uppercase; letter-spacing:.05em; }
    td { padding:14px 8px; border-top:1px solid var(--line); vertical-align:top; }
    td:first-child { color:var(--cyan); font-weight:800; }
    .empty { margin:70px 0; color:var(--muted); text-align:center; line-height:1.5; }
    .proof { margin-top:18px; padding:16px 18px; border-radius:14px; background:#0c1119; color:var(--muted); font-size:16px; line-height:1.35; }
    .proof strong { color:var(--paper); }
    footer { display:flex; justify-content:space-between; gap:20px; margin-top:22px; color:var(--muted); font-size:15px; }
    .pulse { animation:pulse .5s ease; } @keyframes pulse { 50% { scale:1.08; } }
    @media (max-width:720px) { main{padding:28px 20px} h1{font-size:42px}.controls{grid-template-columns:1fr}.summary,.grid{grid-template-columns:1fr}.panel{min-height:auto} }
  </style>
</head>
<body>
<main>
  <div class="eyebrow">Laboratório local · SQLite</div>
  <h1>Uma intenção. Quantos efeitos?</h1>
  <p class="subtitle">Timeout simulado depois do commit. Resultado consultado no SQLite.</p>
  <div class="controls">
    <button data-kind="naive" data-testid="run-naive">Executar sem chave</button>
    <button data-kind="safe" data-testid="run-idempotent">Executar com chave estável</button>
    <button data-kind="conflict" data-testid="run-conflict">Trocar o payload</button>
  </div>
  <section class="summary">
    <div class="metric"><span>Cenário</span><strong id="scenario">aguardando</strong></div>
    <div class="metric"><span id="attemptsLabel">Tentativas</span><strong id="attempts">0</strong></div>
    <div class="metric"><span>Efeitos no banco</span><strong id="effectCount">0</strong></div>
  </section>
  <section class="grid">
    <div class="panel">
      <h2>Sequência ilustrada</h2>
      <div class="timeline" id="timeline"><div class="empty">Execute um cenário para ver cada etapa.</div></div>
    </div>
    <div class="panel">
      <h2>Tabela <code>effects</code></h2>
      <div id="table"><div class="empty">Nenhum efeito persistido.</div></div>
      <div class="proof" id="proof"><strong>Fonte:</strong> leitura da base local após a execução.</div>
    </div>
  </section>
  <footer><span>Dados fictícios · execução reproduzível</span><span id="operation">operation_id: —</span></footer>
</main>
<script>
const wait=(ms)=>new Promise(resolve=>setTimeout(resolve,ms));
const scenario=document.querySelector('#scenario');
const attempts=document.querySelector('#attempts');
const attemptsLabel=document.querySelector('#attemptsLabel');
const effectCount=document.querySelector('#effectCount');
const timeline=document.querySelector('#timeline');
const table=document.querySelector('#table');
const proof=document.querySelector('#proof');
const operation=document.querySelector('#operation');
let busy=false;

function renderRows(rows, emptyMessage='Nenhum efeito persistido.'){
  if(!rows.length){table.innerHTML=`<div class="empty">${emptyMessage}</div>`;return;}
  table.innerHTML=`<table><thead><tr><th>ID</th><th>operation_id</th><th>payload</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${row.id}</td><td>${row.operation_id}</td><td>${row.payload_sha256.slice(0,10)}…</td></tr>`).join('')}</tbody></table>`;
}

async function render(data){
  scenario.textContent=data.title;
  attempts.textContent=data.summary.attempts;
  attemptsLabel.textContent=data.summary.attempts_label||'Tentativas';
  effectCount.textContent=data.summary.effect_count;
  effectCount.className=data.summary.effect_count>1?'danger':'safe';
  operation.textContent=`operation_id: ${data.summary.operation_id}`;
  timeline.innerHTML='';
  renderRows([], data.name==='conflict'
    ? 'Efeito anterior preservado.<br>Nenhum novo efeito criado.'
    : 'Aguardando leitura persistida…');
  for(const [index,event] of data.events.entries()){
    const node=document.createElement('div');
    node.className=`event ${event.tone}`;
    node.innerHTML=`<span class="n">${index+1}</span><span><strong>${event.label}</strong><small>${event.detail}</small></span><span class="tag">${event.tag}</span>`;
    timeline.appendChild(node);
    await wait(560);
    node.classList.add('visible');
  }
  await wait(450);
  renderRows(data.effects);
  effectCount.classList.add('pulse');
  await wait(520);
  effectCount.classList.remove('pulse');
  proof.innerHTML=`<strong>${data.proof}</strong><br>${data.limit}`;
  document.body.dataset.complete=data.name;
}

async function run(name){
  if(busy)return;
  busy=true;
  document.body.dataset.complete='';
  try{
    const response=await fetch(`/api/scenarios/${name}`,{method:'POST'});
    if(!response.ok)throw new Error(await response.text());
    await render(await response.json());
  }finally{busy=false;}
}

document.querySelector('[data-testid="run-naive"]').addEventListener('click',()=>run('naive'));
document.querySelector('[data-testid="run-idempotent"]').addEventListener('click',()=>run('idempotent'));
document.querySelector('[data-testid="run-conflict"]').addEventListener('click',()=>run('conflict'));
window.retryDemo={run};
window.demoReady=true;
</script>
</body>
</html>"""


def _events(name: str) -> list[dict[str, str]]:
    common = [
        {"label": "Primeira tentativa", "detail": "operação enviada à função local", "tag": "request", "tone": "info"},
        {"label": "COMMIT confirmado", "detail": "o efeito já existe no SQLite", "tag": "durável", "tone": "safe"},
        {"label": "Resposta perdida", "detail": "timeout depois do commit", "tag": "timeout", "tone": "danger"},
        {"label": "Retry automático", "detail": "a mesma intenção volta à API", "tag": "tentativa 2", "tone": "info"},
    ]
    if name == "naive":
        return common + [
            {"label": "Segundo efeito criado", "detail": "a repetição não foi reconhecida", "tag": "duplicado", "tone": "danger"}
        ]
    if name == "idempotent":
        return common + [
            {"label": "Chave reconhecida", "detail": "mesma chave e mesmo payload", "tag": "replay", "tone": "safe"},
            {"label": "Nenhum efeito novo", "detail": "a tabela permanece com uma linha", "tag": "protegido", "tone": "safe"},
        ]
    return [
        {"label": "Primeiro efeito registrado", "detail": "chave ticket-demo-001 ligada ao payload original", "tag": "aceito", "tone": "safe"},
        {"label": "Mesma chave reutilizada", "detail": "o valor do payload foi alterado", "tag": "conflito", "tone": "danger"},
        {"label": "Operação rejeitada", "detail": "nenhuma nova linha foi persistida", "tag": "bloqueado", "tone": "safe"},
    ]


class RetryDemoApplication:
    def __init__(self, database: str | Path):
        self.database = Path(database)

    def reset(self) -> None:
        self.database.unlink(missing_ok=True)

    def scenario(self, name: str) -> dict[str, Any]:
        self.reset()
        if name in {"naive", "idempotent"}:
            result = run_operation(
                self.database,
                operation_id="ticket-demo-001",
                payload={"action": "open", "ticket": "TCK-DEMO-001"},
                mode=name,
            )
            title = "sem chave" if name == "naive" else "chave estável"
            proof = (
                "2 tentativas → 2 efeitos persistidos"
                if name == "naive"
                else "2 tentativas → 1 efeito persistido"
            )
            limit = "Leitura feita diretamente da tabela effects após o retry."
        elif name == "conflict":
            operation_id = "ticket-demo-001"
            original = {"action": "open", "ticket": "TCK-DEMO-001"}
            changed = {"action": "open", "ticket": "TCK-DEMO-002"}
            first = run_operation(
                self.database,
                operation_id=operation_id,
                payload=original,
                mode="idempotent",
            )
            try:
                run_operation(
                    self.database,
                    operation_id=operation_id,
                    payload=changed,
                    mode="idempotent",
                )
            except PayloadConflictError:
                pass
            else:  # pragma: no cover - guards the public demonstration
                raise RuntimeError("the conflicting payload was unexpectedly accepted")
            result = {
                **first,
                "attempts": 1,
                "attempts_label": "Tentativas divergentes",
                "status": "payload_conflict",
            }
            title = "payload divergente"
            proof = "Mesma chave + outro payload → rejeitado"
            limit = "A primeira linha permanece; nenhuma segunda mutação foi aceita."
        else:
            raise ValueError(f"unsupported scenario: {name}")

        effects = list_effects(self.database)
        result["effect_count"] = len(effects)
        return {
            "name": name,
            "title": title,
            "summary": result,
            "events": _events(name),
            "effects": effects,
            "proof": proof,
            "limit": limit,
        }

    def state(self) -> dict[str, Any]:
        effects = list_effects(self.database)
        return {"effect_count": len(effects), "effects": effects}


def make_handler(application: RetryDemoApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/":
                encoded = PAGE.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return
            if path == "/api/state":
                self._json(application.state())
                return
            self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/reset":
                application.reset()
                self._json(application.state())
                return
            prefix = "/api/scenarios/"
            if path.startswith(prefix):
                name = path.removeprefix(prefix)
                try:
                    self._json(application.scenario(name))
                except ValueError as error:
                    self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                return
            self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def serve(database: str | Path, host: str, port: int) -> None:
    application = RetryDemoApplication(database)
    server = ThreadingHTTPServer((host, port), make_handler(application))
    print(f"agent-retry-lab serving on http://{host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
