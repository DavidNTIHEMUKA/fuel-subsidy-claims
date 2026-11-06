"""Original illustrations for the Home page slider (drawn for this platform, free to use).
An administrator can replace any of them with a real photo in Admin › Home pictures.

Every scene keeps its main subject on the right half: the left half sits under the welcome text."""
import base64
import random

W, H = 1400, 460

# ---------------------------------------------------------------------------------------------- shared pieces
COMMON_DEFS = """
<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
  <stop offset="0" stop-color="#2F7FC4"/><stop offset=".55" stop-color="#8CC4EC"/><stop offset="1" stop-color="#E8F3FA"/></linearGradient>
<radialGradient id="sun" cx=".5" cy=".5" r=".5">
  <stop offset="0" stop-color="#FFF8D6"/><stop offset=".35" stop-color="#FFF1B0" stop-opacity=".9"/>
  <stop offset="1" stop-color="#FFF1B0" stop-opacity="0"/></radialGradient>
<linearGradient id="far" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8DB9A0"/><stop offset="1" stop-color="#B9D6C4"/></linearGradient>
<linearGradient id="mid" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5BA36A"/><stop offset="1" stop-color="#3E8A50"/></linearGradient>
<linearGradient id="near" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#3D8F48"/><stop offset="1" stop-color="#256B32"/></linearGradient>
<linearGradient id="tar" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5B616B"/><stop offset="1" stop-color="#2E3238"/></linearGradient>
<linearGradient id="glass" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#9FCBEB"/><stop offset=".5" stop-color="#3D79B3"/>
  <stop offset="1" stop-color="#1F4E86"/></linearGradient>
<linearGradient id="mist" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF" stop-opacity="0"/>
  <stop offset=".5" stop-color="#FFFFFF" stop-opacity=".55"/><stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/></linearGradient>
<filter id="blur" x="-20%" y="-50%" width="140%" height="200%"><feGaussianBlur stdDeviation="7"/></filter>
<filter id="soft" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="2"/></filter>
<filter id="shadow" x="-10%" y="-10%" width="130%" height="140%"><feGaussianBlur stdDeviation="5"/></filter>
"""


def _svg(body, extra_defs=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid slice">'
            f'<defs>{COMMON_DEFS}{extra_defs}</defs>{body}</svg>')


def _sky(sun=(1210, 90)):
    s = '<rect width="1400" height="460" fill="url(#sky)"/>'
    if sun:
        s += f'<circle cx="{sun[0]}" cy="{sun[1]}" r="120" fill="url(#sun)"/><circle cx="{sun[0]}" cy="{sun[1]}" r="34" fill="#FFF9E3"/>'
    return s


def _cloud(x, y, s=1.0, op=.92):
    parts = [(0, 0, 70, 26), (-55, 10, 48, 20), (55, 8, 52, 22), (-20, -18, 44, 26), (28, -14, 40, 22)]
    blobs = "".join(f'<ellipse cx="{x+dx*s:.0f}" cy="{y+dy*s:.0f}" rx="{rx*s:.0f}" ry="{ry*s:.0f}"/>'
                    for dx, dy, rx, ry in parts)
    shade = "".join(f'<ellipse cx="{x+dx*s:.0f}" cy="{y+dy*s+10*s:.0f}" rx="{rx*s:.0f}" ry="{ry*s*.55:.0f}"/>'
                    for dx, dy, rx, ry in parts[:3])
    return (f'<g filter="url(#blur)" opacity="{op}"><g fill="#C9DDEE">{shade}</g><g fill="#FFFFFF">{blobs}</g></g>')


def _clouds(seed=1, n=6, top=30, bottom=150):
    rnd = random.Random(seed)
    return "".join(_cloud(rnd.randint(80, 1350), rnd.randint(top, bottom), rnd.uniform(.6, 1.3), rnd.uniform(.75, .95))
                   for _ in range(n))


def _land(base=300):
    """Far, middle and near hills with atmospheric depth."""
    b = base
    return (f'<path d="M0 {b-40} C160 {b-95} 330 {b-80} 470 {b-55} C640 {b-115} 820 {b-120} 980 {b-70} '
            f'C1120 {b-100} 1280 {b-95} 1400 {b-65} V460 H0Z" fill="url(#far)"/>'
            f'<rect x="0" y="{b-90}" width="1400" height="90" fill="url(#mist)"/>'
            f'<path d="M0 {b+5} C220 {b-45} 380 {b-30} 560 {b-10} C760 {b-55} 940 {b-45} 1120 {b-12} '
            f'C1260 {b-35} 1340 {b-28} 1400 {b-22} V460 H0Z" fill="url(#mid)"/>'
            f'<path d="M0 {b+70} C260 {b+45} 520 {b+55} 760 {b+66} C1000 {b+47} 1220 {b+55} 1400 {b+62} V460 H0Z" fill="url(#near)"/>')


def _tree(x, y, s=1.0, c=("#2E7D32", "#388E3C", "#43A047")):
    return (f'<ellipse cx="{x}" cy="{y+26*s}" rx="{20*s}" ry="{4*s}" fill="#000" opacity=".15"/>'
            f'<rect x="{x-3*s}" y="{y}" width="{6*s}" height="{26*s}" fill="#6B4226"/>'
            f'<circle cx="{x}" cy="{y-8*s}" r="{18*s}" fill="{c[0]}"/><circle cx="{x-12*s}" cy="{y+1*s}" r="{12*s}" fill="{c[1]}"/>'
            f'<circle cx="{x+12*s}" cy="{y+1*s}" r="{12*s}" fill="{c[2]}"/><circle cx="{x-5*s}" cy="{y-16*s}" r="{8*s}" fill="#66BB6A" opacity=".6"/>')


def _eucalyptus(x, y, s=1.0):
    return (f'<path d="M{x} {y} L{x+2*s} {y-90*s}" stroke="#D8CDBB" stroke-width="{5*s}"/>'
            f'<ellipse cx="{x+2*s}" cy="{y-95*s}" rx="{16*s}" ry="{34*s}" fill="#4F7F52"/>'
            f'<ellipse cx="{x-6*s}" cy="{y-75*s}" rx="{12*s}" ry="{22*s}" fill="#5E9160"/>'
            f'<ellipse cx="{x+10*s}" cy="{y-70*s}" rx="{11*s}" ry="{20*s}" fill="#456F48"/>')


def _palm(x, y, s=1.0):
    t = f'<path d="M{x} {y} q{-4*s} {-60*s} {6*s} {-120*s}" stroke="#7A5A3A" stroke-width="{7*s}" fill="none"/>'
    cx, cy = x + 6 * s, y - 120 * s
    for dx, dy in ((-60, 10), (-45, -25), (0, -40), (45, -25), (60, 12), (-25, 30), (25, 30)):
        t += (f'<path d="M{cx} {cy} q{dx*s/2} {(dy-25)*s/2} {dx*s} {dy*s}" stroke="#2F8F3A" stroke-width="{9*s}" '
              f'fill="none" stroke-linecap="round"/>')
    return t


def _flag(x, y):
    return (f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y+130}" stroke="#E5E7EB" stroke-width="4"/>'
            f'<path d="M{x+2} {y} q36 -6 72 0 v24 q-36 6 -72 0z" fill="#20603D"/>'
            f'<path d="M{x+2} {y} q36 -6 72 0 v12 q-36 6 -72 0z" fill="#00A1DE"/>'
            f'<path d="M{x+2} {y+12} q36 -6 72 0 v6 q-36 6 -72 0z" fill="#FAD201"/>'
            f'<circle cx="{x+60}" cy="{y+5}" r="4" fill="#E5BE01"/>')


def _bus(x, y, s=1.0, stripe="#1B7A3E", body="#FAFAF7", facing=1):
    """A coaster minibus, side view (facing=1 → right)."""
    g = f'<g transform="translate({x},{y}) scale({s * facing},{s})">'
    g += '<ellipse cx="95" cy="80" rx="105" ry="8" fill="#000" opacity=".22"/>'
    g += '<path d="M0 16 Q0 4 12 4 H160 Q182 4 190 22 L196 48 Q198 66 186 70 H8 Q0 70 0 60Z" fill="' + body + '" stroke="#AEB6C1"/>'
    g += '<path d="M164 10 Q180 12 186 26 L190 42 H164Z" fill="#26364A"/>'
    for i in range(6):
        g += f'<rect x="{10+i*25}" y="12" width="20" height="24" rx="3" fill="#2B3E55"/>'
        g += f'<rect x="{12+i*25}" y="14" width="7" height="20" rx="2" fill="#7FA7C9" opacity=".45"/>'
    g += f'<rect x="0" y="44" width="196" height="7" fill="{stripe}"/><rect x="0" y="53" width="196" height="3" fill="#E8820E"/>'
    g += '<rect x="186" y="56" width="10" height="6" rx="2" fill="#FDE68A"/>'
    for wx in (40, 152):
        g += f'<circle cx="{wx}" cy="70" r="13" fill="#1F2328"/><circle cx="{wx}" cy="70" r="6" fill="#B8BEC6"/>'
    return g + '</g>'


def _road_flat(y=410):
    return (f'<rect x="0" y="{y}" width="1400" height="{460-y}" fill="url(#tar)"/>'
            + "".join(f'<rect x="{x}" y="{y+22}" width="54" height="5" rx="2" fill="#F2F2F2"/>' for x in range(20, 1400, 110))
            + f'<rect x="0" y="{y-6}" width="1400" height="6" fill="#C9CFD6"/>')


def _building(x, y, w, h, name, accent="#E8820E", side=True):
    s = f'<rect x="{x+8}" y="{y+10}" width="{w}" height="{h}" rx="6" fill="#000" opacity=".18" filter="url(#shadow)"/>'
    s += f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="#EEF2F7"/>'
    s += f'<rect x="{x+10}" y="{y+42}" width="{w-20}" height="{h-62}" fill="url(#glass)"/>'
    cols, rows = int((w - 30) / 32), int((h - 74) / 24)
    for r in range(rows):
        for c in range(cols):
            s += f'<rect x="{x+16+c*32}" y="{y+48+r*24}" width="2" height="18" fill="#EEF2F7" opacity=".55"/>'
        s += f'<rect x="{x+10}" y="{y+66+r*24}" width="{w-20}" height="2" fill="#EEF2F7" opacity=".55"/>'
    s += f'<path d="M{x+10} {y+42} L{x+w*0.55} {y+42} L{x+10} {y+h*0.75}Z" fill="#FFFFFF" opacity=".12"/>'
    s += f'<rect x="{x}" y="{y}" width="{w}" height="36" rx="6" fill="#0B2B57"/><rect x="{x}" y="{y+32}" width="{w}" height="5" fill="{accent}"/>'
    s += (f'<text x="{x+w/2}" y="{y+24}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="17" '
          f'font-weight="700" fill="#FFFFFF" letter-spacing="1.5">{name}</text>')
    s += f'<rect x="{x+w/2-36}" y="{y+h-48}" width="72" height="48" fill="#0B2B57"/><rect x="{x+w/2-2}" y="{y+h-48}" width="4" height="48" fill="#5B7FA8"/>'
    s += f'<rect x="{x-24}" y="{y+h}" width="{w+48}" height="10" fill="#D5DBE3"/>'
    return s


def _lawn(y=392):
    return (f'<path d="M640 {y} H1400 V412 H640Z" fill="#4CAF50"/>'
            + "".join(f'<circle cx="{x}" cy="{y+8}" r="5" fill="{c}"/>' for x, c in
                      zip(range(660, 1400, 38), ["#E8820E", "#F7B733", "#FFFFFF", "#E85D75"] * 30)))


# ---------------------------------------------------------------------------------------------- scenes
def rura():
    b = _sky() + _clouds(3) + _land(300)
    b += _building(800, 140, 300, 252, "RURA", accent="#1B7A3E")
    b += ('<rect x="1150" y="166" width="200" height="206" rx="12" fill="#0B2B57"/>'
          '<rect x="1150" y="166" width="200" height="36" rx="12" fill="#1B7A3E"/>'
          '<text x="1250" y="190" text-anchor="middle" font-family="Arial" font-size="15" font-weight="700" fill="#fff">PUMP PRICES</text>')
    for i, (p, v) in enumerate([("DIESEL", "2,927"), ("PETROL", "2,938"), ("SUBSIDY", "438")]):
        b += (f'<text x="1166" y="{236+i*44}" font-family="Arial" font-size="14" fill="#CFE3F7">{p}</text>'
              f'<rect x="1256" y="{218+i*44}" width="82" height="28" rx="4" fill="#0F172A"/>'
              f'<text x="1297" y="{238+i*44}" text-anchor="middle" font-family="Courier New, monospace" font-size="17" '
              f'font-weight="700" fill="{"#F7B733" if p != "SUBSIDY" else "#4ADE80"}">{v}</text>')
    b += '<rect x="1243" y="372" width="14" height="38" fill="#6B7280"/>'
    b += _lawn() + _flag(752, 200) + _tree(730, 372, 1.2) + _tree(1124, 380, .9) + _road_flat()
    return _svg(b)


def rra():
    b = _sky((1260, 80)) + _clouds(5) + _land(300)
    b += _building(740, 112, 380, 280, "RWANDA REVENUE AUTHORITY")
    b += _building(1150, 196, 180, 196, "RRA", accent="#1B7A3E")
    b += _lawn() + _flag(690, 190) + _tree(668, 372, 1.25) + _tree(1360, 376, 1.05) + _road_flat()
    return _svg(b)


def minecofin():
    b = _sky((1240, 85)) + _clouds(8) + _land(300)
    x, y, w, h = 760, 150, 420, 242
    b += f'<rect x="{x+8}" y="{y+40}" width="{w}" height="{h-40}" fill="#000" opacity=".18" filter="url(#shadow)"/>'
    b += f'<polygon points="{x-20},{y+40} {x+w/2},{y-22} {x+w+20},{y+40}" fill="#0B2B57"/>'
    b += f'<rect x="{x-20}" y="{y+40}" width="{w+40}" height="14" fill="#E8820E"/>'
    b += (f'<text x="{x+w/2}" y="{y+28}" text-anchor="middle" font-family="Arial" font-size="18" font-weight="700" '
          f'fill="#fff" letter-spacing="2">MINECOFIN</text>')
    b += f'<rect x="{x}" y="{y+54}" width="{w}" height="{h-54}" fill="#F3F6FA"/>'
    for k in range(8):
        cx = x + 22 + k * 54
        b += f'<rect x="{cx}" y="{y+64}" width="18" height="{h-84}" fill="#DCE3EC"/><rect x="{cx}" y="{y+64}" width="6" height="{h-84}" fill="#FFFFFF" opacity=".7"/>'
        b += f'<rect x="{cx-4}" y="{y+60}" width="26" height="8" fill="#C3CCD8"/>'
    b += f'<rect x="{x+w/2-34}" y="{y+h-70}" width="68" height="70" fill="#0B2B57"/>'
    b += f'<rect x="{x-40}" y="{y+h}" width="{w+80}" height="10" fill="#CBD5E1"/>'
    for k, (cx, cy) in enumerate(((1250, 340), (1290, 352), (1330, 340))):
        for j in range(3 + k):
            b += f'<ellipse cx="{cx}" cy="{cy - j*9}" rx="22" ry="8" fill="#F7B733" stroke="#C98A12"/>'
    b += _lawn(402) + _flag(712, 210) + _tree(690, 380, 1.1) + _road_flat(412)
    return _svg(b)


def mininfra():
    b = _sky((1300, 90)) + _clouds(11) + _land(300)
    b += _building(760, 132, 320, 260, "MININFRA")
    b += '<rect x="1110" y="320" width="290" height="12" fill="#6B7280"/>'
    b += '<path d="M1110 320 Q1255 226 1400 320" fill="none" stroke="#E8820E" stroke-width="7"/>'
    b += "".join(f'<line x1="{x}" y1="{320 - max(0, 94 - abs(x - 1255) * 0.65):.0f}" x2="{x}" y2="320" stroke="#9CA3AF" stroke-width="2"/>'
                 for x in range(1130, 1390, 20))
    b += '<rect x="1150" y="332" width="14" height="78" fill="#6B7280"/><rect x="1346" y="332" width="14" height="78" fill="#6B7280"/>'
    b += _flag(712, 196) + _tree(690, 372, 1.15) + _road_flat()
    b += _bus(320, 350, 1.0, stripe="#E8820E")
    return _svg(b)


def kigali_road():
    """A clean, palm-lined Kigali boulevard climbing between green hills and modern towers."""
    b = _sky((1220, 80)) + _clouds(13, 7) + _land(290)
    for x, w, h in ((640, 44, 120), (690, 34, 165), (730, 54, 100), (1000, 40, 140), (1046, 58, 112), (1110, 36, 175), (1152, 48, 96)):
        y = 270 - h
        b += f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="url(#glass)" opacity=".92"/>'
        b += "".join(f'<rect x="{x}" y="{y+8+r*14}" width="{w}" height="2" fill="#E6F0F8" opacity=".5"/>' for r in range(int(h / 14)))
    b += '<path d="M0 300 C240 262 460 270 700 286 C940 268 1180 270 1400 282 V460 H0Z" fill="url(#mid)"/>'
    b += '<polygon points="640,290 760,290 1400,460 0,460" fill="url(#tar)"/>'
    b += '<polygon points="692,290 708,290 770,460 630,460" fill="#43A047"/>'
    for y, sz in ((300, 3), (318, 4), (342, 5), (372, 6), (410, 8), (450, 10)):
        off = (y - 290) * 0.13
        b += f'<circle cx="{700-off}" cy="{y}" r="{sz}" fill="#E8820E"/><circle cx="{700+off}" cy="{y+3}" r="{sz*0.8}" fill="#F7B733"/>'
    for k in range(7):
        t = k / 6
        yl = 300 + t * 150
        b += f'<rect x="{560 - t*520}" y="{yl}" width="{8 + t*30}" height="{2 + t*4}" fill="#F2F2F2"/>'
        b += f'<rect x="{830 + t*480}" y="{yl}" width="{8 + t*30}" height="{2 + t*4}" fill="#F2F2F2"/>'
    b += '<polygon points="0,330 610,290 640,290 0,400" fill="#DAD6CD"/><polygon points="1400,330 790,290 760,290 1400,400" fill="#DAD6CD"/>'
    for x, y, sc in ((520, 310, .45), (380, 330, .65), (180, 362, .9), (880, 310, .45), (1020, 330, .65), (1230, 362, .9)):
        b += _palm(x, y, sc)
    b += _bus(780, 352, 1.05, stripe="#1B7A3E")
    return _svg(b)


def nyabugogo():
    """Nyabugogo bus park: rows of coaster buses and travellers in front of Kigali's green hills."""
    rnd = random.Random(21)
    b = _sky((1240, 70)) + _clouds(17, 6, 20, 110)
    b += ('<path d="M0 230 C200 170 420 180 600 210 C780 160 1000 160 1180 200 C1300 180 1360 186 1400 190 V460 H0Z" fill="url(#far)"/>'
          '<path d="M0 262 C240 222 470 230 700 250 C930 222 1160 228 1400 240 V460 H0Z" fill="url(#mid)"/>')
    # city texture on the hills: soft blocks, no icons
    for _ in range(220):
        x, y = rnd.randint(0, 1400), rnd.randint(205, 262)
        b += (f'<rect x="{x}" y="{y}" width="{rnd.randint(5, 12)}" height="{rnd.randint(3, 7)}" '
              f'fill="{rnd.choice(["#E8E2D6", "#D9D2C4", "#F2EEE6", "#C9BFAE"])}" opacity=".75"/>')
    b += '<rect x="0" y="200" width="1400" height="70" fill="url(#mist)" opacity=".6"/>'
    # terminal building with canopy
    b += ('<rect x="560" y="226" width="840" height="56" fill="#E9EDF2"/>'
          '<rect x="560" y="220" width="840" height="10" fill="#1F5FA8"/>'
          + "".join(f'<rect x="{x}" y="240" width="40" height="26" fill="#9BB8D3"/>' for x in range(580, 1400, 62))
          + '<rect x="1060" y="150" width="56" height="132" fill="#E8820E"/><rect x="1060" y="150" width="56" height="16" fill="#C2410C"/>'
          '<text x="1088" y="230" text-anchor="middle" font-family="Arial" font-size="12" font-weight="800" fill="#fff" '
          'transform="rotate(-90 1088 230)">NYABUGOGO</text>')
    # wet tarmac yard
    b += '<polygon points="0,282 1400,282 1400,460 0,460" fill="url(#tar)"/>'
    b += '<polygon points="0,282 1400,282 1400,300 0,300" fill="#FFFFFF" opacity=".06"/>'
    stripes = ["#1B7A3E", "#E8820E", "#0B2B57", "#1F5FA8", "#C0392B", "#F7B733"]
    # three rows of buses, back to front
    for row, (y, s, n, x0) in enumerate(((282, .48, 11, 600), (316, .66, 8, 560), (360, .9, 5, 540))):
        for k in range(n):
            x = x0 + k * (215 * s + 14)
            if x > 1400:
                break
            b += _bus(x, y, s, stripe=stripes[(k + row) % len(stripes)], facing=1)
    # travellers and umbrellas
    for _ in range(26):
        x, y = rnd.randint(560, 1390), rnd.choice([308, 350, 400, 440])
        sc = .7 if y < 330 else (.85 if y < 380 else 1.0)
        col = rnd.choice(["#E8820E", "#1F5FA8", "#C0392B", "#F7B733", "#FFFFFF", "#7C3AED", "#1B7A3E"])
        b += (f'<circle cx="{x}" cy="{y-26*sc}" r="{5*sc}" fill="#5B3A29"/>'
              f'<rect x="{x-5*sc}" y="{y-21*sc}" width="{10*sc}" height="{16*sc}" rx="{3*sc}" fill="{col}"/>'
              f'<rect x="{x-4*sc}" y="{y-5*sc}" width="{3*sc}" height="{8*sc}" fill="#333"/>'
              f'<rect x="{x+1*sc}" y="{y-5*sc}" width="{3*sc}" height="{8*sc}" fill="#333"/>')
        if rnd.random() < .35:
            uc = rnd.choice(["#E8820E", "#FFFFFF", "#E85D75"])
            b += f'<path d="M{x-16*sc} {y-30*sc} Q{x} {y-50*sc} {x+16*sc} {y-30*sc}Z" fill="{uc}"/>'
    return _svg(b)


def tea_road():
    """A road winding through bright tea fields on terraced hills, with a bus on its way."""
    b = _sky((1180, 70)) + _clouds(23, 6, 25, 120)
    b += ('<path d="M0 200 C150 150 320 160 470 190 C650 130 860 128 1030 180 C1180 150 1320 158 1400 170 V460 H0Z" fill="url(#far)"/>'
          '<rect x="0" y="150" width="1400" height="110" fill="url(#mist)"/>'
          '<path d="M0 250 C200 210 380 216 560 244 C760 200 960 206 1160 238 C1280 222 1350 226 1400 232 V460 H0Z" fill="url(#mid)"/>')
    for k in range(10):
        y = 252 + k * 12
        b += (f'<path d="M0 {y+18} C200 {y-24} 380 {y-16} 560 {y+10} C760 {y-34} 960 {y-28} 1160 {y+5} '
              f'C1280 {y-10} 1350 {y-6} 1400 {y-2}" stroke="#7CC576" stroke-width="6" fill="none" stroke-linecap="round" opacity=".75"/>')
    b += '<path d="M0 322 C260 294 520 302 760 316 C1000 296 1220 302 1400 310 V460 H0Z" fill="url(#near)"/>'
    for k in range(11):
        y = 330 + k * 12
        b += (f'<path d="M0 {y} C300 {y-14} 600 {y-6} 900 {y-12} C1100 {y-16} 1300 {y-8} 1400 {y-10}" '
              f'stroke="#8FD18A" stroke-width="8" fill="none" stroke-linecap="round" opacity=".9"/>'
              f'<path d="M0 {y+4} C300 {y-10} 600 {y-2} 900 {y-8} C1100 {y-12} 1300 {y-4} 1400 {y-6}" '
              f'stroke="#2E7D32" stroke-width="2" fill="none" opacity=".5"/>')
    b += ('<path d="M930 252 C880 276 1010 292 960 318 C900 350 720 372 690 460 L1040 460 C1040 400 1170 366 1110 330 '
          'C1060 302 960 288 960 252 Z" fill="url(#tar)"/>'
          '<path d="M945 254 C925 280 1010 294 978 320 C930 354 840 386 862 460" stroke="#F2C94C" stroke-width="4" '
          'fill="none" stroke-dasharray="18 14"/>')
    b += _bus(930, 300, .62, stripe="#1B7A3E")
    for x, y, sc in ((1230, 330, 1.0), (1290, 338, 1.15), (1350, 326, .95), (640, 300, .7), (600, 306, .8)):
        b += _eucalyptus(x, y, sc)
    return _svg(b)


def growth():
    defs = ('<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0E4A2C"/>'
            '<stop offset="1" stop-color="#1B7A3E"/></linearGradient>'
            '<linearGradient id="arrow" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#F7B733"/>'
            '<stop offset="1" stop-color="#FDE68A"/></linearGradient>')
    b = '<rect width="1400" height="460" fill="url(#bg)"/>'
    b += "".join(f'<line x1="{x}" y1="40" x2="{x}" y2="420" stroke="#FFFFFF" stroke-opacity=".06"/>' for x in range(0, 1400, 70))
    b += "".join(f'<line x1="0" y1="{y}" x2="1400" y2="{y}" stroke="#FFFFFF" stroke-opacity=".06"/>' for y in range(40, 460, 60))
    for i, h in enumerate([90, 130, 120, 170, 210, 250]):
        b += f'<rect x="{760+i*70}" y="{410-h}" width="44" height="{h}" rx="6" fill="#FFFFFF" opacity=".18"/>'
    b += ('<rect x="1210" y="150" width="130" height="250" rx="16" fill="#F3F4F6"/>'
          '<rect x="1228" y="175" width="94" height="58" rx="6" fill="#0B2B57"/>'
          '<text x="1275" y="212" text-anchor="middle" font-family="Courier New, monospace" font-size="22" font-weight="700" fill="#4ADE80">438</text>'
          '<rect x="1236" y="250" width="78" height="10" rx="5" fill="#1B7A3E"/><rect x="1236" y="270" width="78" height="10" rx="5" fill="#E8820E"/>'
          '<rect x="1196" y="398" width="158" height="16" rx="6" fill="#D1D5DB"/>'
          '<path d="M1340 200 C1390 210 1392 280 1372 320 L1372 360" fill="none" stroke="#374151" stroke-width="9"/>'
          '<rect x="1360" y="356" width="26" height="40" rx="6" fill="#374151"/>')
    b += ('<path d="M740 380 L860 320 L930 345 L1040 250 L1110 270 L1190 160" fill="none" stroke="url(#arrow)" '
          'stroke-width="16" stroke-linecap="round" stroke-linejoin="round"/><polygon points="1215,128 1160,150 1205,190" fill="#FDE68A"/>')
    return _svg(b, defs)


def data_uri(svg: str) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


SLIDES = [
    ("rura", "RURA · Rwanda Utilities Regulatory Authority",
     "Official pump prices and the fuel subsidy per litre come from the regulator.", rura),
    ("rra", "RRA · Rwanda Revenue Authority",
     "Every claim line is verified against EBM receipts before any subsidy is paid.", rra),
    ("minecofin", "MINECOFIN · Ministry of Finance and Economic Planning",
     "Funds the fuel subsidy and co-chairs the interministerial taskforce.", minecofin),
    ("mininfra", "MININFRA · Ministry of Infrastructure",
     "Transport policy and the roads that connect every district.", mininfra),
    ("nyabugogo", "Nyabugogo, the heart of public transport",
     "Thousands of travellers a day — the subsidy keeps their fares stable.", nyabugogo),
    ("kigali", "Kigali on the move",
     "Clean, green boulevards served by public transport.", kigali_road),
    ("rural", "Through the tea hills",
     "From Kigali to every district, buses keep rural Rwanda connected.", tea_road),
    ("growth", "Fast, transparent reimbursement",
     "Submit, verify, sign and pay in one place — every step tracked.", growth),
]
