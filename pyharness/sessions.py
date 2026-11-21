"""Session persistence: one JSON file per session in myPyHarnessSessions/."""
import json
import os
import re
import secrets
import time

ID_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}$")
FOLDER = "myPyHarnessSessions"


class SessionStore:
    def __init__(self, path):
        self.path = os.path.abspath(path)

    @staticmethod
    def new_id():
        return time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2)

    def _file(self, sid):
        if not isinstance(sid, str) or not ID_RE.match(sid):
            raise ValueError("invalid session id")
        return os.path.join(self.path, sid + ".json")

    def save(self, s):
        s["updated"] = time.time()
        os.makedirs(self.path, exist_ok=True)
        f = self._file(s["id"])
        tmp = f + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(s, fh, ensure_ascii=False)
        os.replace(tmp, f)

    def load(self, sid):
        with open(self._file(sid), "r", encoding="utf-8") as fh:
            return json.load(fh)

    def list(self):
        out = []
        try:
            names = os.listdir(self.path)
        except OSError:
            return out
        for n in names:
            if not n.endswith(".json"):
                continue
            try:
                s = self.load(n[:-5])
                out.append({"id": s["id"], "title": s.get("title") or "",
                            "updated": s.get("updated", 0), "root": s.get("root", ""),
                            "root_exists": os.path.isdir(s.get("root", ""))})
            except (OSError, ValueError, KeyError):
                continue
        return sorted(out, key=lambda x: x["updated"], reverse=True)
