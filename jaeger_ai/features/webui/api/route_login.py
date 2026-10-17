"""Login page HTML generation, redirection validation, and locale handling.

Extracted from routes.py to isolate self-contained presentation and security logic.
"""
from __future__ import annotations

import html as _html
import os
import re
from urllib.parse import parse_qs, quote, unquote

# ── Login page locale strings ─────────────────────────────────────────────────
# The key matches the 'language' setting value (from static/i18n.js LOCALES).
_LOGIN_LOCALE = {
    "en": {
        "lang": "en",
        "title": "Sign in",
        "subtitle": "Enter your password to continue",
        "placeholder": "Password",
        "btn": "Sign in",
        "invalid_pw": "Invalid password",
        "conn_failed": "Connection failed",
    },
    "fr": {
        "lang": "fr-FR",
        "title": "Se connecter",
        "subtitle": "Entrez votre mot de passe pour continuer",
        "placeholder": "Mot de passe",
        "btn": "Se connecter",
        "invalid_pw": "Mot de passe invalide",
        "conn_failed": "\u00c9chec de la connexion",
    },
    "es": {
        "lang": "es-ES",
        "title": "Iniciar sesi\u00f3n",
        "subtitle": "Introduce tu contrase\u00f1a para continuar",
        "placeholder": "Contrase\u00f1a",
        "btn": "Entrar",
        "invalid_pw": "Contrase\u00f1a inv\u00e1lida",
        "conn_failed": "Error de conexi\u00f3n",
    },
    "de": {
        "lang": "de-DE",
        "title": "Anmelden",
        "subtitle": "Geben Sie Ihr Passwort ein, um fortzufahren",
        "placeholder": "Passwort",
        "btn": "Anmelden",
        "invalid_pw": "Ung\u00fcltiges Passwort",
        "conn_failed": "Verbindung fehlgeschlagen",
    },
    "ru": {
        "lang": "ru-RU",
        "title": "\u0412\u043e\u0439\u0442\u0438",
        "subtitle": "\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043f\u0430\u0440\u043e\u043b\u044c, \u0447\u0442\u043e\u0431\u044b \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u0442\u044c",
        "placeholder": "\u041f\u0430\u0440\u043e\u043b\u044c",
        "btn": "\u0412\u043e\u0439\u0442\u0438",
        "invalid_pw": "\u041d\u0435\u0432\u0435\u0440\u043d\u044b\u0439 \u043f\u0430\u0440\u043e\u043b\u044c",
        "conn_failed": "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0438\u0442\u044c\u0441\u044f",
    },
    "zh": {
        "lang": "zh-CN",
        "title": "\u767b\u5f55",
        "subtitle": "\u8f93\u5165\u5bc6\u7801\u7ee7\u7eed\u4f7f\u7528",
        "placeholder": "\u5bc6\u7801",
        "btn": "\u767b\u5f55",
        "invalid_pw": "\u5bc6\u7801\u9519\u8bef",
        "conn_failed": "\u8fde\u63a5\u5931\u8d25",
    },
    "zh-Hant": {
        "lang": "zh-TW",
        "title": "\u767b\u5f55",
        "subtitle": "\u8f38\u5165\u5bc6\u78bc\u7e7c\u7e8c\u4f7f\u7528",
        "placeholder": "\u5bc6\u78bc",
        "btn": "\u767b\u5f55",
        "invalid_pw": "\u5bc6\u78bc\u932f\u8aa4",
        "conn_failed": "\u9023\u63a5\u5931\u6557",
    },
    "it": {
        "lang": "it-IT",
        "title": "Accedi",
        "subtitle": "Inserisci la password per continuare",
        "placeholder": "Password",
        "btn": "Accedi",
        "invalid_pw": "Password non valida",
        "conn_failed": "Connessione fallita",
    },
    "ja": {
        "lang": "ja-JP",
        "title": "\u30b5\u30a4\u30f3\u30a4\u30f3",
        "subtitle": "\u30d1\u30b9\u30ef\u30fc\u30c9\u3092\u5165\u529b\u3057\u3066\u7d9a\u884c",
        "placeholder": "\u30d1\u30b9\u30ef\u30fc\u30c9",
        "btn": "\u30b5\u30a4\u30f3\u30a4\u30f3",
        "invalid_pw": "\u30d1\u30b9\u30ef\u30fc\u30c9\u304c\u7121\u52b9\u3067\u3059",
        "conn_failed": "\u63a5\u7d9a\u5931\u6557",
    },
    "pt": {
        "lang": "pt-BR",
        "title": "Entrar",
        "subtitle": "Digite sua senha para continuar",
        "placeholder": "Senha",
        "btn": "Entrar",
        "invalid_pw": "Senha inv\u00e1lida",
        "conn_failed": "Falha na conex\u00e3o",
    },
    "ko": {
        "lang": "ko-KR",
        "title": "\ub85c\uadf8\uc778",
        "subtitle": "\uacc4\uc18d\ud558\ub824\uba74 \ube44\ubc00\ubc88\ud638\ub97c \uc785\ub825\ud558\uc138\uc694",
        "placeholder": "\ube44\ubc00\ubc88\ud638",
        "btn": "\ub85c\uadf8\uc778",
        "invalid_pw": "\ube44\ubc00\ubc88\ud638\uac00 \uc62c\ubc14\ub974\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4",
        "conn_failed": "\uc5f0\uacb0 \uc2e4\ud328",
    },
    "tr": {
        "lang": "tr-TR",
        "title": "Oturum a\u00e7",
        "subtitle": "Devam etmek i\u00e7in \u015fifrenizi girin",
        "placeholder": "\u015eifre",
        "btn": "Oturum a\u00e7",
        "invalid_pw": "Ge\u00e7ersiz \u015fifre",
        "conn_failed": "Ba\u011flant\u0131 ba\u015far\u0131s\u0131z",
    },
    "pl": {
        "lang": "pl-PL",
        "title": "Zaloguj si\u0119",
        "subtitle": "Wpisz has\u0142o, aby kontynuowa\u0107",
        "placeholder": "Has\u0142o",
        "btn": "Zaloguj si\u0119",
        "invalid_pw": "Nieprawid\u0142owe has\u0142o",
        "conn_failed": "Po\u0142\u0105czenie nie powiod\u0142o si\u0119",
    },
    "vi": {
        "lang": "vi",
        "title": "\u0110\u0103ng nh\u1eadp",
        "subtitle": "Nh\u1eadp m\u1eadt kh\u1ea9u c\u1ee7a b\u1ea1n \u0111\u1ec3 ti\u1ebfp t\u1ee5c",
        "placeholder": "M\u1eadt kh\u1ea9u",
        "btn": "\u0110\u0103ng nh\u1eadp",
        "invalid_pw": "M\u1eadt kh\u1ea9u kh\u00f4ng h\u1ee3p l\u1ec7",
        "conn_failed": "K\u1ebft n\u1ed1i th\u1ea5t b\u1ea1i",
    },
    "cs": {
        "lang": "cs-CZ",
        "title": "P\u0159ihl\u00e1sit se",
        "subtitle": "Zadejte heslo pro pokra\u010dov\u00e1n\u00ed",
        "placeholder": "Heslo",
        "btn": "P\u0159ihl\u00e1sit se",
        "invalid_pw": "Neplatn\u00e9 heslo",
        "conn_failed": "P\u0159ipojen\u00ed selhalo",
    },
}


def _resolve_login_locale_key(raw_lang: str | None) -> str:
    """Resolve settings.language to a known _LOGIN_LOCALE key."""
    if not raw_lang:
        return "en"
    lang = str(raw_lang).strip()
    if not lang:
        return "en"
    if lang in _LOGIN_LOCALE:
        return lang

    normalized = lang.replace("_", "-")
    lower = normalized.lower()

    for key in _LOGIN_LOCALE:
        if key.lower() == lower:
            return key

    if lower == "zh" or lower.startswith("zh-cn") or lower.startswith("zh-sg") or lower.startswith("zh-hans"):
        return "zh"
    if lower.startswith("zh-tw") or lower.startswith("zh-hk") or lower.startswith("zh-mo") or lower.startswith("zh-hant"):
        return "zh-Hant" if "zh-Hant" in _LOGIN_LOCALE else "zh"

    base = lower.split("-", 1)[0]
    for key in _LOGIN_LOCALE:
        if key.lower() == base:
            return key
    return "en"


# ── Login page (self-contained, no external deps) ────────────────────────────
_LOGIN_PAGE_HTML = """<!doctype html>
<html lang="{{LANG}}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{BOT_NAME}} — {{LOGIN_TITLE}}</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#1a1a2e;color:#e8e8f0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  height:100vh;display:flex;align-items:center;justify-content:center}
.card{background:#16213e;border:1px solid rgba(255,255,255,.08);border-radius:16px;padding:36px 32px;
  width:320px;text-align:center;box-shadow:0 8px 32px rgba(0,0,0,.3)}
.logo{width:48px;height:48px;border-radius:12px;background:linear-gradient(145deg,#e8a030,#e94560);
  display:flex;align-items:center;justify-content:center;font-weight:800;font-size:20px;color:#fff;
  margin:0 auto 12px;box-shadow:0 2px 12px rgba(233,69,96,.3)}
h1{font-size:18px;font-weight:600;margin-bottom:4px}
.sub{font-size:12px;color:#8888aa;margin-bottom:24px}
input{width:100%;padding:10px 14px;border-radius:10px;border:1px solid rgba(255,255,255,.1);
  background:rgba(255,255,255,.04);color:#e8e8f0;font-size:14px;outline:none;margin-bottom:14px;
  transition:border-color .15s}
input:focus{border-color:rgba(124,185,255,.5);box-shadow:0 0 0 3px rgba(124,185,255,.1)}
button{width:100%;padding:10px;border-radius:10px;border:none;background:rgba(124,185,255,.15);
  border:1px solid rgba(124,185,255,.3);color:#7cb9ff;font-size:14px;font-weight:600;cursor:pointer;
  transition:all .15s}
button:hover{background:rgba(124,185,255,.25)}
.oidc-login{display:block;margin-top:10px;padding:10px;border-radius:10px;text-decoration:none;
  background:rgba(255,255,255,.04);border:1px solid rgba(111,214,164,.35);color:#6fd6a4;
  font-size:14px;font-weight:600;cursor:pointer;transition:all .15s}
.oidc-login:hover{background:rgba(111,214,164,.12)}
.passkey-login{margin-top:10px;background:rgba(255,255,255,.04);border-color:rgba(232,160,48,.35);color:#e8a030}
.err{color:#e94560;font-size:12px;margin-top:10px;display:none}
</style></head><body>
<div class="card">
  <div class="logo">{{BOT_NAME_INITIAL}}</div>
  <h1>{{BOT_NAME}}</h1>
  <p class="sub">{{LOGIN_SUBTITLE}}</p>
  <form id="login-form" data-invalid-pw="{{LOGIN_INVALID_PW}}" data-conn-failed="{{LOGIN_CONN_FAILED}}">
    <input type="password" id="pw" placeholder="{{LOGIN_PLACEHOLDER}}" autofocus>
    <button type="submit">{{LOGIN_BTN}}</button>
    <button type="button" id="passkey-login" class="passkey-login" style="display:none">Sign in with passkey</button>
    {{OIDC_LOGIN_HTML}}
  </form>
  <div class="err" id="err"></div>
</div>
<!-- Keep login.js relative so subpath mounts load it under the current scope. -->
<script src="static/login.js?v={{WEBUI_VERSION}}"></script>
</body></html>"""


def _safe_login_redirect_path(raw_path: str | None) -> str:
    path = str(raw_path or "").strip()
    if not path:
        return "/"
    if path[0] != "/":
        return "/"
    if path[1:2] in {"/", "\\"}:
        return "/"
    if re.search(r"[\x00-\x1f\x7f\s]", path):
        return "/"
    if len(path) > 2048:
        return "/"
    _probe = path
    for _ in range(8):
        _path_only = _probe.split("?", 1)[0].split("#", 1)[0].split("&", 1)[0].rstrip("/")
        if _path_only.endswith("/login") or _path_only == "/login":
            return "/"
        _decoded = unquote(_probe)
        if _decoded == _probe:
            break
        _probe = _decoded
    else:
        _path_only = _probe.split("?", 1)[0].split("#", 1)[0].split("&", 1)[0].rstrip("/")
        if _path_only.endswith("/login") or _path_only == "/login":
            return "/"
        return "/"
    return path


def _request_base_url(handler) -> str:
    from api.auth import _is_secure_context

    scheme = "https" if _is_secure_context(handler) else "http"
    host = str(handler.headers.get("Host") or "").strip() or "127.0.0.1:8790"
    return f"{scheme}://{host}"


def _oidc_login_html(parsed) -> str:
    try:
        from api.auth_oidc import is_oidc_enabled
    except Exception:
        return ""
    if not is_oidc_enabled():
        return ""
    next_path = _safe_login_redirect_path(
        parse_qs(parsed.query or "").get("next", [""])[0]
    )
    href = "/api/auth/oidc/start"
    if next_path != "/":
        href += "?next=" + quote(next_path, safe="/")
    return (
        '<a id="oidc-login" class="oidc-login" '
        f'href="{_html.escape(href, quote=True)}">Continue with SSO</a>'
    )


def handle_login_page(handler, parsed, *, load_settings_fn, render_html_fn) -> bool:
    """Render the localized, self-contained HTML login page."""
    _settings = load_settings_fn()
    _bn = _html.escape(_settings.get("bot_name") or "Jaeger")
    _lang = _settings.get("language", "en")
    _login_strings = _LOGIN_LOCALE[_resolve_login_locale_key(_lang)]
    from api.updates import WEBUI_VERSION
    version_token = quote(WEBUI_VERSION, safe="")
    _page = (
        _LOGIN_PAGE_HTML.replace("{{BOT_NAME}}", _bn)
        .replace("{{BOT_NAME_INITIAL}}", _bn[0].upper())
        .replace("{{WEBUI_VERSION}}", version_token)
        .replace("{{LANG}}", _html.escape(_login_strings["lang"]))
        .replace("{{LOGIN_TITLE}}", _html.escape(_login_strings["title"]))
        .replace("{{LOGIN_SUBTITLE}}", _html.escape(_login_strings["subtitle"]))
        .replace("{{LOGIN_PLACEHOLDER}}", _html.escape(_login_strings["placeholder"]))
        .replace("{{LOGIN_BTN}}", _html.escape(_login_strings["btn"]))
        .replace("{{LOGIN_INVALID_PW}}", _html.escape(_login_strings["invalid_pw"]))
        .replace("{{LOGIN_CONN_FAILED}}", _html.escape(_login_strings["conn_failed"]))
        .replace("{{OIDC_LOGIN_HTML}}", _oidc_login_html(parsed))
    )
    return render_html_fn(handler, _page, content_type="text/html; charset=utf-8")

