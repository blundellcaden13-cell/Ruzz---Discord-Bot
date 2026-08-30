import os
import base64
from html import escape

SITE_NAME = "Amplified SMP"

_ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def _data_uri(filename: str, mime: str) -> str | None:
    """Read an image from static/ and inline it as a base64 data URI,
    so every page is self-contained — no /static route, no extra
    Cloudflare rule, and it can never show up broken because a static
    file route wasn't wired up. Swap the image by replacing the file
    in static/; nothing else needs to change."""
    path = os.path.join(_ASSET_DIR, filename)
    try:
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    except (FileNotFoundError, OSError):
        return None


LOGO_DATA_URI = _data_uri("logo.jpg", "image/jpeg")
BACKGROUND_DATA_URI = _data_uri("background.jpg", "image/jpeg")

BASE_CSS = """
:root{
  --bg:#0a0a0a; --bg-alt:#111111; --panel:#161616; --panel2:#1e1e1e;
  --border:#2c2c2c; --border-soft:#232323;
  --text:#f2ede6; --muted:#9a9088; --muted-dim:#615a53;
  --accent:#ff8c1a; --accent-hover:#e87c0e; --accent-soft:rgba(255,140,26,.15);
  --danger:#ef4655; --danger-soft:rgba(239,70,85,.15);
  --success:#2fbf71; --success-soft:rgba(47,191,113,.15);
  --warn:#f5c518; --warn-soft:rgba(245,197,24,.15);
  --radius:12px; --radius-sm:8px;
  --shadow:0 8px 24px rgba(0,0,0,.5);
}
*{box-sizing:border-box;}
body{margin:0;font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
color:var(--text);min-height:100vh;
background:
  linear-gradient(180deg, rgba(10,8,5,.88), rgba(10,10,10,.96) 55%, var(--bg) 85%),
  url('__BACKGROUND_URI__') center 30% / cover no-repeat fixed,
  var(--bg);
}
.wrap{max-width:1240px;margin:0 auto;padding:0 24px 60px;}
a{color:inherit;text-decoration:none;}
code{background:var(--panel2);padding:2px 7px;border-radius:5px;font-size:12px;border:1px solid var(--border-soft);}

.navbar{display:flex;align-items:center;justify-content:center;padding:22px 24px;
border-bottom:1px solid var(--border-soft);margin-bottom:32px;
background:linear-gradient(180deg,rgba(255,140,26,.06),transparent);}
.navbar .brand{display:flex;align-items:center;gap:12px;font-weight:800;font-size:19px;letter-spacing:-.01em;}
.navbar .brand .logo-img{width:36px;height:36px;border-radius:9px;object-fit:cover;box-shadow:0 0 0 2px var(--accent),0 4px 14px rgba(255,140,26,.35);}
.navbar .brand .dot{width:36px;height:36px;border-radius:9px;background:linear-gradient(135deg,var(--accent),#ffb15c);
display:flex;align-items:center;justify-content:center;font-size:17px;box-shadow:0 4px 14px rgba(255,140,26,.35);}

header.top{display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:24px;flex-wrap:wrap;gap:14px;}
h1{font-size:24px;margin:0;letter-spacing:-.02em;font-weight:700;}
h1 .sub{color:var(--muted);font-weight:500;font-size:13px;display:block;margin-top:6px;letter-spacing:0;}

.btn{display:inline-flex;align-items:center;gap:6px;padding:10px 18px;border-radius:var(--radius-sm);
background:var(--accent);color:#1a0f00;font-weight:700;font-size:13.5px;border:none;cursor:pointer;
font-family:inherit;transition:.15s;box-shadow:0 2px 10px rgba(255,140,26,.3);}
.btn:hover{background:var(--accent-hover);transform:translateY(-1px);}
.btn.secondary{background:var(--panel2);border:1px solid var(--border);color:var(--text);box-shadow:none;font-weight:600;}
.btn.secondary:hover{background:#262626;transform:none;}
.btn.danger{background:var(--danger);color:#fff;box-shadow:0 2px 8px rgba(239,70,85,.25);}
.btn.danger:hover{background:#d63a48;}
.btn.small{padding:7px 12px;font-size:12.5px;}

.nav{display:flex;gap:8px;align-items:center;flex-wrap:wrap;}
.card{background:linear-gradient(180deg,var(--panel),var(--bg-alt));border:1px solid var(--border);
border-radius:var(--radius);padding:26px;box-shadow:var(--shadow);}

.banner{padding:14px 18px;border-radius:var(--radius-sm);margin-bottom:20px;font-size:13.5px;line-height:1.5;
border:1px solid transparent;}
.banner.warn{background:var(--danger-soft);border-color:rgba(239,70,85,.35);}
.banner.info{background:var(--accent-soft);border-color:rgba(255,140,26,.35);}
.banner.ok{background:var(--success-soft);border-color:rgba(47,191,113,.35);}

.pill{display:inline-block;padding:3px 11px;border-radius:20px;font-size:10.5px;font-weight:800;
text-transform:uppercase;letter-spacing:.04em;vertical-align:middle;}
.pill.pending{background:var(--accent-soft);color:#ffb15c;}
.pill.posted{background:var(--success-soft);color:#6fe0a0;}
.pill.failed{background:var(--danger-soft);color:#ff9a9c;}
.pill.online{background:var(--success-soft);color:#6fe0a0;}
.pill.maintenance{background:var(--warn-soft);color:#f5c518;}
.pill.offline{background:var(--danger-soft);color:#ff9a9c;}
.pill.error{background:var(--danger-soft);color:#ff9a9c;}

footer.foot{margin-top:48px;text-align:center;color:var(--muted-dim);font-size:11.5px;}
footer.foot .foot-nav{display:flex;gap:18px;justify-content:center;margin-bottom:10px;}
footer.foot .foot-nav a{color:var(--muted);font-weight:600;font-size:12px;transition:.15s;}
footer.foot .foot-nav a:hover{color:var(--accent);}
footer.foot .foot-nav a.active{color:var(--accent);}

/* Login shell, reused wherever a site has its own login page */
.login-shell{max-width:400px;margin:64px auto 0;}
.login-shell .brand-lockup{display:flex;flex-direction:column;align-items:center;gap:10px;margin-bottom:28px;}
.login-shell .brand-lockup .badge{width:52px;height:52px;border-radius:16px;background:linear-gradient(135deg,var(--accent),#ffb15c);
display:flex;align-items:center;justify-content:center;font-size:24px;box-shadow:0 8px 24px rgba(255,140,26,.35);}
.login-shell .brand-lockup img.badge{object-fit:cover;}
form.form label{display:block;margin:18px 0 6px;font-size:12.5px;font-weight:700;color:var(--muted);
text-transform:uppercase;letter-spacing:.03em;}
form.form input[type=text],form.form input[type=password],form.form input[type=date],
form.form input[type=time],form.form select,form.form textarea{
width:100%;padding:11px 14px;border-radius:var(--radius-sm);border:1px solid var(--border);
background:var(--bg-alt);color:var(--text);font-size:14px;font-family:inherit;transition:.15s;}
form.form input:focus,form.form select:focus,form.form textarea:focus{outline:none;border-color:var(--accent);
box-shadow:0 0 0 3px var(--accent-soft);}

/* Landing-page cards (home.py) */
.card-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px;margin-bottom:28px;}
.stat-card{display:flex;flex-direction:column;gap:4px;}
.stat-card .label{font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:700;}
.stat-card .value{font-size:26px;font-weight:800;letter-spacing:-.02em;}
.stat-card .value.small{font-size:16px;font-weight:700;}
.stat-dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;vertical-align:middle;}
.stat-dot.online{background:var(--success);box-shadow:0 0 10px var(--success);}
.stat-dot.maintenance{background:var(--warn);box-shadow:0 0 10px var(--warn);}
.stat-dot.offline,.stat-dot.error{background:var(--danger);box-shadow:0 0 10px var(--danger);}

.tool-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px;}
.tool-card{display:flex;flex-direction:column;gap:10px;border-top:2px solid var(--accent);}
.tool-card h3{margin:0;font-size:17px;}
.tool-card .meta{display:flex;gap:8px;flex-wrap:wrap;}
.tool-card .meta span{font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;
padding:3px 9px;border-radius:20px;background:var(--panel2);color:var(--muted);border:1px solid var(--border-soft);}
.tool-card .meta span.rank-admin{background:var(--warn-soft);color:#f5c518;border-color:rgba(245,197,24,.3);}
.tool-card .meta span.rank-public{background:var(--success-soft);color:#6fe0a0;border-color:rgba(47,191,113,.3);}
.tool-card p{margin:0;color:var(--muted);font-size:13.5px;line-height:1.55;flex:1;}

.opt-summary{display:flex;flex-direction:column;gap:8px;margin:12px 0 0;}
.opt-summary .opt{background:var(--panel2);border:1px solid var(--border-soft);padding:10px 14px;
border-radius:8px;font-size:13.5px;display:flex;gap:10px;align-items:center;}
.opt-summary .opt b{color:var(--accent);}

/* Logs viewer */
.log-pane{background:#000;border:1px solid var(--border);border-radius:var(--radius);padding:18px 20px;
font-family:'SF Mono',Menlo,Consolas,monospace;font-size:12.5px;line-height:1.65;max-height:70vh;overflow-y:auto;
white-space:pre-wrap;word-break:break-word;}
.log-line{border-bottom:1px solid rgba(255,255,255,.03);padding:2px 0;}
.log-line.lvl-ERROR{color:#ff8a8f;}
.log-line.lvl-WARNING{color:#f5c518;}
.log-line.lvl-INFO{color:#c7cad1;}
.log-line.lvl-DEBUG{color:#6b6f7b;}
"""

BASE_CSS = BASE_CSS.replace("__BACKGROUND_URI__", BACKGROUND_DATA_URI or "")


def navbar(brand_name: str = None, brand_icon_url: str = None) -> str:
    """Just the site identity — no cross-site nav links up here anymore
    (those live in the footer instead, see layout())."""
    name = escape(brand_name or SITE_NAME)
    icon_url = brand_icon_url or LOGO_DATA_URI or ""
    logo = f'<img class="logo-img" src="{escape(icon_url)}" alt="">'

    return f"""
    <div class="navbar">
      <div class="brand">{logo} {name}</div>
    </div>
    """


def footer_nav(active: str) -> str:
    def link(path, label, key):
        cls = "active" if key == active else ""
        return f'<a class="{cls}" href="{path}">{label}</a>'

    return f"""
    <div class="foot-nav">
      {link("/home", "Home", "home")}
      {link("/polls", "Polls", "polls")}
      {link("/tickets", "Tickets", "tickets")}
      {link("/logs", "Logs", "logs")}
    </div>
    """


def layout(
    title: str, body: str, active: str = "",
    brand_name: str = None, brand_icon_url: str = None, extra_css: str = "",
) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} • {SITE_NAME}</title>
<style>{BASE_CSS}{extra_css}</style></head>
<body>
{navbar(brand_name, brand_icon_url)}
<div class="wrap">
{body}
<footer class="foot">
{footer_nav(active)}
{SITE_NAME} — {escape(title)}
</footer>
</div></body></html>"""
