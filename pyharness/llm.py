"""Streaming client for the Codex (ChatGPT backend) Responses endpoint."""
import json
import time
import urllib.error
import urllib.request
import uuid

BASE_URL = "https://chatgpt.com/backend-api/codex"


CLIENT_VERSIONS = ("99.0.0", "0.130.0")  # the models endpoint filters by client version


class LLMError(Exception):
    pass


class Cancelled(Exception):
    pass


def _headers(auth, accept="application/json"):
    token, account = auth.token()
    h = {"Authorization": f"Bearer {token}", "Accept": accept, "OpenAI-Beta": "responses=experimental",
         "originator": "codex_cli_rs", "User-Agent": "pyharness/0.1"}
    if account:
        h["chatgpt-account-id"] = account
    return h


def get_json(auth, url, extra_headers=None):
    for attempt in range(2):
        h = _headers(auth)
        h.update(extra_headers or {})
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt == 0:
                auth.refresh(force=True)
                continue
            raise LLMError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}")
        except urllib.error.URLError as e:
            raise LLMError(f"Network error: {e.reason}")
        except ValueError:
            raise LLMError("Invalid JSON from server")


def fetch_models(auth, base_url=None):
    """Models this ChatGPT account may use: [{slug, name, efforts, default_effort}], best first."""
    base, last, data = base_url or BASE_URL, None, None
    for ver in CLIENT_VERSIONS:
        try:
            data = get_json(auth, f"{base}/models?client_version={ver}")
            break
        except LLMError as e:
            last = e
    if data is None:
        raise last
    raw = data.get("models", []) if isinstance(data, dict) else data
    out = []
    for m in raw if isinstance(raw, list) else []:
        if not isinstance(m, dict):
            continue
        slug = m.get("slug") or m.get("id") or m.get("model")
        if not isinstance(slug, str) or m.get("visibility") in ("hide", "hidden", "none"):
            continue
        efforts = []
        for lv in m.get("supported_reasoning_levels") or m.get("supported_reasoning_efforts") or []:
            e = lv.get("effort") if isinstance(lv, dict) else lv
            if isinstance(e, str) and e not in efforts:
                efforts.append(e)
        efforts = efforts or ["low", "medium", "high"]
        d = m.get("default_reasoning_level") or m.get("default_reasoning_effort")
        if d not in efforts:
            d = "medium" if "medium" in efforts else efforts[0]
        pr = m.get("priority")
        out.append({"slug": slug, "name": m.get("display_name") or slug, "efforts": efforts,
                    "default_effort": d, "_p": pr if isinstance(pr, (int, float)) else 999})
    out.sort(key=lambda x: x["_p"])
    for m in out:
        del m["_p"]
    return out


def stream(auth, model, instructions, input_items, tools, on_delta, cancel,
           effort="medium", base_url=None):
    """Run one model turn. Returns (output_items, usage)."""
    base_url = base_url or BASE_URL
    body = json.dumps({
        "model": model,
        "instructions": instructions,
        "input": input_items,
        "tools": tools,
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "store": False,
        "stream": True,
        "include": ["reasoning.encrypted_content"],
        "reasoning": {"effort": effort},
    }).encode("utf-8")

    resp = None
    for attempt in range(3):
        headers = _headers(auth, "text/event-stream")
        headers["Content-Type"] = "application/json"
        headers["session_id"] = str(uuid.uuid4())
        req = urllib.request.Request(base_url + "/responses", data=body, headers=headers, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=120)
            break
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")[:1500]
            if e.code == 401 and attempt == 0:
                auth.refresh(force=True)
                continue
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise LLMError(f"HTTP {e.code}: {text}")
        except urllib.error.URLError as e:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise LLMError(f"Network error: {e.reason}")
    if resp is None:
        raise LLMError("No response")

    items, usage, completed, data = [], None, False, []
    with resp:
        for raw in resp:
            if cancel.is_set():
                raise Cancelled()
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith("data:"):
                data.append(line[5:].lstrip())
                continue
            if line or not data:
                continue
            payload, data = "\n".join(data), []
            if payload == "[DONE]":
                break
            try:
                ev = json.loads(payload)
            except ValueError:
                continue
            t = ev.get("type", "")
            if t == "response.output_text.delta":
                on_delta(ev.get("delta", ""))
            elif t == "response.output_item.done":
                items.append(ev["item"])
            elif t == "response.completed":
                usage = (ev.get("response") or {}).get("usage")
                completed = True
                break
            elif t in ("response.failed", "error"):
                err = (ev.get("response") or {}).get("error") or ev.get("error") or ev
                raise LLMError(f"Model error: {err.get('message', err) if isinstance(err, dict) else err}")
            elif t == "response.incomplete":
                completed = True
                break
    if not completed and not items:
        raise LLMError("Stream ended without a response.")
    return items, usage
