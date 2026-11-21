"""Usage / rate-limit status for the ChatGPT Codex plan (unofficial endpoint, parsed defensively)."""
import json
import time

from . import llm

USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"


def fetch_usage(auth):
    return llm.get_json(auth, USAGE_URL, {"User-Agent": "codex-cli", "OAI-Product-Sku": "codex"})


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _first(d, *keys):
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return None


def windows(p):
    """-> [(used_percent, window_minutes|None, reset_epoch|None)]"""
    out, now = [], time.time()

    def add(w):
        if not isinstance(w, dict):
            return
        used = _num(_first(w, "used_percent", "usedPercent"))
        if used is None:
            return
        mins = _num(_first(w, "window_duration_mins", "windowDurationMins"))
        if mins is None and _num(_first(w, "limit_window_seconds", "limitWindowSeconds")) is not None:
            mins = _num(_first(w, "limit_window_seconds", "limitWindowSeconds")) / 60
        reset = _num(_first(w, "reset_at", "resetAt", "resets_at", "resetsAt"))
        if reset and reset > 1e12:
            reset /= 1000
        after = _num(_first(w, "reset_after_seconds", "resetAfterSeconds"))
        if reset is None and after is not None:
            reset = now + after
        out.append((max(0.0, min(100.0, used)), mins, reset))

    rl = p.get("rate_limit") or p.get("rateLimit")
    if isinstance(rl, dict):
        add(_first(rl, "primary_window", "primaryWindow", "primary"))
        add(_first(rl, "secondary_window", "secondaryWindow", "secondary"))
    if not out:
        rls = p.get("rate_limits") or p.get("rateLimits")
        if isinstance(rls, dict):
            add(rls.get("primary"))
            add(rls.get("secondary"))
    return out


def _label(mins):
    if mins is None:
        return "Janela"
    if abs(mins - 300) < 5:
        return "Janela de 5 horas"
    if abs(mins - 10080) < 60:
        return "Janela semanal"
    return f"Janela de {mins / 60:.0f} h" if mins >= 120 else f"Janela de {mins:.0f} min"


def _remaining(ts):
    secs = int(ts - time.time())
    if secs <= 0:
        return "agora"
    d, r = divmod(secs, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    parts = ([f"{d}d"] if d else []) + ([f"{h}h"] if h else []) + ([f"{m}min"] if m or not (d or h) else [])
    return "em " + " ".join(parts) + time.strftime(" (%d/%m %H:%M)", time.localtime(ts))


def format_status(payload, error, who, model, effort, tokens):
    lines = ["📊 Status de uso"]
    meta = []
    if who:
        meta.append(f"conta {who}")
    if isinstance(payload, dict) and payload.get("plan_type"):
        meta.append(f"plano {payload['plan_type']}")
    if meta:
        lines.append(" · ".join(meta))
    lines.append(f"Modelo: {model or '(nenhum)'} · nível: {effort}")
    if error:
        lines.append(f"Não foi possível obter o uso da conta: {error}")
    elif isinstance(payload, dict):
        ws = windows(payload)
        for used, mins, reset in ws:
            s = f"• {_label(mins)}: {used:.0f}% usado · {100 - used:.0f}% disponível"
            if reset:
                s += f" · renova {_remaining(reset)}"
            lines.append(s)
        if not ws:
            lines.append("Formato de resposta desconhecido:\n" + json.dumps(payload, ensure_ascii=False)[:800])
    lines.append(f"Tokens nesta sessão: {tokens.get('in', 0)} entrada · {tokens.get('out', 0)} saída")
    return "\n".join(lines)
