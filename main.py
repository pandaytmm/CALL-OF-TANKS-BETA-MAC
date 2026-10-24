import hashlib
import itertools
import json
import math
import os
import platform
import queue
import random
import re
import socket
import subprocess
import sys
import threading
import uuid

import pygame

__version__ = "1.0.0"
# python-for-android ortamini algila.
ANDROID = (sys.platform == "android" or bool(os.environ.get("ANDROID_ARGUMENT"))
           or bool(os.environ.get("ANDROID_PRIVATE")))

pygame.init()
window = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
SW, SH = window.get_size()
# Oyun her bilgisayarda ayni 1920x1080'lik mantiksal dunyada calisir (coklu oyuncu icin sart).
# Ekranin boyutu farkliysa goruntu orantili olarak olceklenir.
W, H = 1920, 1080
screen = pygame.Surface((W, H))
VIEW_SCALE = min(SW / W, SH / H)
VIEW_W, VIEW_H = int(W * VIEW_SCALE), int(H * VIEW_SCALE)
VIEW_X, VIEW_Y = (SW - VIEW_W) // 2, (SH - VIEW_H) // 2
view_surf = pygame.Surface((VIEW_W, VIEW_H)) if (VIEW_W, VIEW_H) != (W, H) else None
window.fill((0, 0, 0))
pygame.display.set_caption("Tank Savaşı")


def to_logical(pos):
    """Pencere koordinatini oyun dunyasi koordinatina cevirir."""
    return ((pos[0] - VIEW_X) / VIEW_SCALE, (pos[1] - VIEW_Y) / VIEW_SCALE)


def present():
    if view_surf is None:
        window.blit(screen, (VIEW_X, VIEW_Y))
    else:
        pygame.transform.smoothscale(screen, (VIEW_W, VIEW_H), view_surf)
        window.blit(view_surf, (VIEW_X, VIEW_Y))
    pygame.display.flip()

clock = pygame.time.Clock()

FONT = "arial"
font = pygame.font.SysFont(FONT, 24, bold=True)
small = pygame.font.SysFont(FONT, 20)
tiny = pygame.font.SysFont(FONT, 18, bold=True)
micro = pygame.font.SysFont(FONT, 15, bold=True)
name_font = pygame.font.SysFont(FONT, 26, bold=True)
big = pygame.font.SysFont(FONT, 72, bold=True)
mid = pygame.font.SysFont(FONT, 32, bold=True)

# ---------------- AYARLAR ----------------
BOSS_EVERY = 10      # her 10. levelde boss gelir (dalgalar sonsuz)
UPGRADE_EVERY = 1    # kac levelde bir 3 secenek sunulsun
if getattr(sys, "frozen", False):          # exe olarak calisiyorsa
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def get_save_dir():
    """Yazilabilir bir kayit klasoru bulur (AppData / Application Support), olmazsa oyunun klasoru."""
    home = os.path.expanduser("~")
    if ANDROID:
        # Android uygulamasinin yazilabilir, uygulamaya ozel klasoru.
        base = os.environ.get("ANDROID_PRIVATE") or home
    elif sys.platform == "darwin":                    # macOS
        base = os.path.join(home, "Library", "Application Support")
    elif sys.platform.startswith("win"):              # Windows
        base = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    else:                                              # Linux
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    for d in (os.path.join(base, "TankSavasi"), BASE_DIR):
        try:
            os.makedirs(d, exist_ok=True)
            test = os.path.join(d, ".yazma_testi")
            with open(test, "w") as f:
                f.write("ok")
            os.remove(test)
            return d
        except OSError:
            continue
    return BASE_DIR


SAVE_PATH = os.path.join(get_save_dir(), "tank_kayit.json")
OLD_SAVE_PATH = os.path.join(BASE_DIR, "tank_kayit.json")   # eski surumden kalan kayit
save_error = False
new_pc_notice = False   # yeni bilgisayar algilandiysa menude uyari gosterilir


# ---------------- yardimci fonksiyonlar ----------------
def angle_diff(a, b):
    return (b - a + math.pi) % (2 * math.pi) - math.pi


def clamp(v, lo=0, hi=255):
    return max(lo, min(hi, v))


def shade(c, f):
    return (clamp(int(c[0] * f)), clamp(int(c[1] * f)), clamp(int(c[2] * f)))


def lerp_color(c1, c2, t):
    t = clamp(t, 0, 1)
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def is_boss_level(l):
    return l % BOSS_EVERY == 0


def ball(surf, x, y, r, color):
    """Parlak top (sadece tas ve ikon gibi detaylar icin; tanklar artik cokgenlerden olusur)."""
    x, y, r = int(x), int(y), max(3, int(r))
    pygame.draw.circle(surf, shade(color, 0.4), (x, y), r)
    pygame.draw.circle(surf, color, (x, y), r - 1)
    pygame.draw.circle(surf, shade(color, 1.6), (x - r // 3, y - r // 3), max(1, r // 3))


# ---------------- tank cizimi (cokgenler) ----------------
STEEL = (80, 84, 92)
_shadow_cache = {}


def get_shadow(s):
    key = round(s, 2)
    if key not in _shadow_cache:
        w, h = int(130 * s), int(92 * s)
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.ellipse(surf, (0, 0, 0, 38), (0, 0, w, h))
        pygame.draw.ellipse(surf, (0, 0, 0, 45), (w * 0.1, h * 0.1, w * 0.8, h * 0.8))
        _shadow_cache[key] = surf
    return _shadow_cache[key]


def rpts(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def poly(surf, color, pts, x, y, a, s, outline=None, off=(0, 0)):
    c, sn = math.cos(a), math.sin(a)
    wp = [(x + off[0] + (px * c - py * sn) * s, y + off[1] + (px * sn + py * c) * s) for px, py in pts]
    pygame.draw.polygon(surf, color, wp)
    if outline:
        pygame.draw.polygon(surf, outline, wp, max(1, int(2 * s)))


def pline(surf, color, p1, p2, x, y, a, s, w=1):
    c, sn = math.cos(a), math.sin(a)
    w1 = (x + (p1[0] * c - p1[1] * sn) * s, y + (p1[0] * sn + p1[1] * c) * s)
    w2 = (x + (p2[0] * c - p2[1] * sn) * s, y + (p2[0] * sn + p2[1] * c) * s)
    pygame.draw.line(surf, color, w1, w2, max(1, int(w * s)))


def make_spec(main, dark, accent, hl=1.0, hw=1.0, tur=1.0, barrel_len=34, barrel_w=7, twin=False):
    return dict(main=main, dark=dark, accent=accent, hl=hl, hw=hw, tur=tur,
                barrel_len=barrel_len, barrel_w=barrel_w, twin=twin,
                muzzle=22 * tur + barrel_len + 6, r=int(30 * max(hl, hw)))


def draw_tank(surf, x, y, body_a, turret_a, spec, s=1.0, recoil=0.0, flash=0.0, tread=0.0):
    """Gercekci gorunumlu tank: paletler, egimli govde, motor izgarasi, kule, namlu, agiz freni."""
    def fl(c):
        return lerp_color(c, (255, 255, 255), flash) if flash > 0 else c

    main, dark, accent = fl(spec["main"]), fl(spec["dark"]), fl(spec["accent"])
    steel = fl(STEEL)
    hl, hw, T = spec["hl"], spec["hw"], spec["tur"]
    depth = (3 * s, 4 * s)

    shd = get_shadow(s)
    surf.blit(shd, (int(x - shd.get_width() / 2 + 8 * s), int(y - shd.get_height() / 2 + 12 * s)))

    # --- paletler ---
    tx0, tx1 = -38 * hl, 38 * hl
    for side in (-1, 1):
        ya, yb = sorted((side * 13 * hw, side * 27 * hw))
        pts = [(tx0 + 6, ya), (tx1 - 6, ya), (tx1, ya + 6), (tx1, yb - 6),
               (tx1 - 6, yb), (tx0 + 6, yb), (tx0, yb - 6), (tx0, ya + 6)]
        poly(surf, (16, 17, 20), pts, x, y, body_a, s, off=depth)
        poly(surf, fl((56, 58, 64)), pts, x, y, body_a, s, outline=(20, 21, 24))
        span = (tx1 - tx0) - 12
        for k in range(int(span // 7) + 1):
            px = tx0 + 6 + ((k * 7 + tread) % span)
            pline(surf, (30, 31, 35), (px, ya + 1.5), (px, yb - 1.5), x, y, body_a, s, 2)
        pline(surf, fl((96, 99, 108)), (tx0 + 8, (ya + yb) / 2), (tx1 - 8, (ya + yb) / 2), x, y, body_a, s, 1)

    # --- govde ---
    hx0, hx1 = -34 * hl, 36 * hl
    hh = 17 * hw
    cut = 12 * hl
    hull = [(hx0, -hh + 2), (hx1 - cut, -hh), (hx1, -hh * 0.5), (hx1, hh * 0.5),
            (hx1 - cut, hh), (hx0, hh - 2), (hx0 - 3, hh * 0.6), (hx0 - 3, -hh * 0.6)]
    poly(surf, shade(dark, 0.5), hull, x, y, body_a, s, off=depth)
    poly(surf, main, hull, x, y, body_a, s, outline=shade(dark, 0.55))
    poly(surf, shade(main, 1.14), [(px * 0.86, py * 0.78) for px, py in hull], x, y, body_a, s)
    pline(surf, shade(dark, 0.7), (hx1 - cut, -hh), (hx1 - cut, hh), x, y, body_a, s, 2)

    # motor izgarasi (arka)
    ex0, ex1 = hx0 + 3, hx0 + 22 * hl
    poly(surf, shade(dark, 0.95), rpts(ex0, -hh * 0.62, ex1, hh * 0.62), x, y, body_a, s)
    gx = ex0 + 3
    while gx < ex1:
        pline(surf, shade(dark, 0.45), (gx, -hh * 0.55), (gx, hh * 0.55), x, y, body_a, s, 1)
        gx += 4

    # yan camurluklar, seritler, farlar
    for side in (-1, 1):
        poly(surf, shade(dark, 0.8), rpts(hx0 + 10, side * (hh - 1), hx1 - cut - 2, side * (hh + 3)),
             x, y, body_a, s)
        pline(surf, accent, (hx0 + 26 * hl, side * hh * 0.55), (hx1 - cut - 6, side * hh * 0.55),
              x, y, body_a, s, 3)
        poly(surf, (255, 240, 175), rpts(hx1 - 5, side * hh * 0.3, hx1 - 1, side * hh * 0.5), x, y, body_a, s)

    # --- namlu(lar) ---
    ys = (-5.5, 5.5) if spec["twin"] else (0,)
    bw, bl = spec["barrel_w"], spec["barrel_len"]
    bx0 = 22 * T - recoil
    bx1 = 22 * T + bl - recoil
    for yy in ys:
        poly(surf, (16, 17, 20), rpts(bx0, yy - bw / 2, bx1, yy + bw / 2), x, y, turret_a, s, off=depth)
        poly(surf, steel, rpts(bx0, yy - bw / 2, bx1, yy + bw / 2), x, y, turret_a, s,
             outline=shade(steel, 0.45))
        poly(surf, shade(steel, 1.5), rpts(bx0, yy - bw / 2 + 1, bx1 - 2, yy - bw * 0.1), x, y, turret_a, s)
        poly(surf, shade(steel, 0.8), rpts(bx1 - 7, yy - bw / 2 - 1.5, bx1 + 2, yy + bw / 2 + 1.5),
             x, y, turret_a, s, outline=shade(steel, 0.4))

    # --- kule ---
    base = [(-17, -12), (6, -15), (17, -9), (17, 9), (6, 15), (-17, 12), (-23, 6), (-23, -6)]
    tur = [(px * T, py * T) for px, py in base]
    poly(surf, shade(dark, 0.45), tur, x, y, turret_a, s, off=depth)
    poly(surf, shade(main, 1.05), tur, x, y, turret_a, s, outline=shade(dark, 0.5))
    poly(surf, shade(main, 1.3), [(px * 0.78, py * 0.74) for px, py in tur], x, y, turret_a, s)
    poly(surf, shade(dark, 0.8), rpts(-15 * T, -6 * T, -5 * T, 6 * T), x, y, turret_a, s)
    poly(surf, shade(main, 0.9), rpts(-13.5 * T, -4.5 * T, -6.5 * T, 4.5 * T), x, y, turret_a, s)
    poly(surf, accent, [(2 * T, -5 * T), (10 * T, 0), (2 * T, 5 * T)], x, y, turret_a, s)
    poly(surf, shade(main, 0.78), rpts(14 * T, -8 * T, 24 * T, 8 * T), x, y, turret_a, s,
         outline=shade(dark, 0.5))
    pline(surf, (25, 25, 28), (-20 * T, 8 * T), (-36 * T, 22 * T), x, y, turret_a, s, 1)


# ---------------- tank cesitleri (dukkanda satilir) ----------------
TANKS = [
    dict(id="acemi", name="Acemi", price=0, hp=100, speed=260, cooldown=0.45, dmg=20,
         bullet_speed=650, shots=1, regen=0.0, desc="Dengeli başlangıç tankı",
         spec=make_spec((76, 148, 84), (40, 88, 50), (225, 225, 130))),
    dict(id="golge", name="Gölge", price=400, hp=80, speed=340, cooldown=0.36, dmg=16,
         bullet_speed=700, shots=1, regen=0.0, desc="Çok hızlı ve çevik",
         spec=make_spec((88, 110, 190), (45, 58, 115), (160, 220, 255), hl=0.95, hw=0.88, tur=0.92,
                        barrel_len=32, barrel_w=6)),
    dict(id="demir", name="Demir Kale", price=1000, hp=220, speed=200, cooldown=0.55, dmg=26,
         bullet_speed=650, shots=1, regen=0.0, desc="Ağır zırhlı, çok dayanıklı",
         spec=make_spec((110, 120, 96), (62, 70, 54), (205, 172, 62), hl=1.05, hw=1.2, tur=1.15,
                        barrel_len=36, barrel_w=9)),
    dict(id="keskin", name="Keskin", price=2000, hp=110, speed=240, cooldown=0.9, dmg=70,
         bullet_speed=1000, shots=1, regen=0.0, desc="Yavaş ama çok güçlü atış",
         spec=make_spec((196, 160, 96), (120, 92, 48), (90, 60, 30), hl=1.1, hw=0.95, tur=0.95,
                        barrel_len=54, barrel_w=6)),
    dict(id="ikiz", name="İkiz Top", price=3500, hp=150, speed=250, cooldown=0.4, dmg=22,
         bullet_speed=700, shots=2, regen=0.0, desc="Çift namlu, çift mermi",
         spec=make_spec((214, 120, 50), (125, 62, 22), (255, 232, 150), hw=1.05, tur=1.05,
                        barrel_len=36, barrel_w=6, twin=True)),
    dict(id="firtina", name="Fırtına", price=5500, hp=130, speed=280, cooldown=0.22, dmg=14,
         bullet_speed=800, shots=1, regen=0.0, desc="Çok hızlı atış yapar",
         spec=make_spec((205, 52, 56), (92, 20, 26), (255, 255, 255), hw=0.95, barrel_len=30, barrel_w=6)),
    dict(id="kral", name="Kral", price=9000, hp=260, speed=270, cooldown=0.3, dmg=40,
         bullet_speed=800, shots=2, regen=1.0, desc="Her şeyde en iyisi",
         spec=make_spec((232, 192, 62), (112, 86, 22), (34, 34, 40), hl=1.12, hw=1.15, tur=1.15,
                        barrel_len=46, barrel_w=8, twin=True)),
]
MAX_TANK_LEVEL = 10

TANKS.extend([
    dict(id="kobra", name="Kobra", price=7500, hp=140, speed=300, cooldown=0.30, dmg=28,
         bullet_speed=900, shots=1, regen=0.0, desc="Mermileri düşmanları deler",
         preset={"pierce": 1},
         spec=make_spec((38, 156, 96), (16, 72, 44), (255, 232, 70), hl=1.05, hw=0.92, tur=0.98,
                        barrel_len=50, barrel_w=6)),
    dict(id="vampir", name="Vampir", price=12000, hp=170, speed=265, cooldown=0.38, dmg=30,
         bullet_speed=760, shots=1, regen=0.0, desc="Verdiği hasarla can kazanır",
         preset={"lifesteal": 0.08},
         spec=make_spec((132, 30, 62), (60, 14, 32), (235, 235, 240), hw=1.05, tur=1.05,
                        barrel_len=38, barrel_w=7)),
    dict(id="havan", name="Patlatıcı", price=16000, hp=210, speed=225, cooldown=0.70, dmg=55,
         bullet_speed=680, shots=1, regen=0.0, desc="Mermisi patlar, çevreye hasar verir",
         preset={"splash": 0.5},
         spec=make_spec((168, 98, 38), (86, 46, 16), (255, 205, 80), hl=1.05, hw=1.15, tur=1.12,
                        barrel_len=34, barrel_w=13)),
    dict(id="titan", name="Titan", price=22000, hp=450, speed=175, cooldown=0.60, dmg=46,
         bullet_speed=720, shots=2, regen=2.0, desc="Dev gibi dayanıklı, kalkanlı",
         preset={"shield": 3},
         spec=make_spec((92, 112, 152), (44, 54, 82), (255, 200, 60), hl=1.2, hw=1.3, tur=1.25,
                        barrel_len=40, barrel_w=10, twin=True)),
    dict(id="hayalet", name="Hayalet", price=30000, hp=170, speed=410, cooldown=0.25, dmg=26,
         bullet_speed=950, shots=2, regen=0.0, desc="Seken çift mermi, ışık hızında",
         preset={"bounces": 2},
         spec=make_spec((212, 226, 238), (108, 128, 150), (80, 222, 255), hl=0.95, hw=0.85, tur=0.9,
                        barrel_len=52, barrel_w=5, twin=True)),
])

# Gizli tank (ADMINTANKS koduyla acilir): her sey full
ADMIN_TANK = dict(
    id="admin", name="ADMIN TANK", price=0, hp=2000, speed=460, cooldown=0.12, dmg=150,
    bullet_speed=1400, shots=5, regen=15.0, desc="Yönetici tankı: her şey full",
    preset={"bounces": 4, "pierce": 3, "lifesteal": 0.4, "splash": 1.4, "shield": 9,
            "shock": 4, "crit": 0.5, "gold": 1.0, "slow": 3, "burn": 3},
    spec=make_spec((24, 24, 32), (214, 170, 34), (255, 60, 60), hl=1.2, hw=1.2, tur=1.2,
                   barrel_len=58, barrel_w=9, twin=True))
TANK_BY_ID = {t["id"]: t for t in TANKS + [ADMIN_TANK]}

STAT_KEYS = ["max_hp", "hp", "speed", "cooldown", "dmg", "bullet_speed", "shots", "bounces", "regen", "shield",
            "pierce", "lifesteal", "splash", "shock", "crit", "gold", "slow", "burn"]


# ---------------- kayit sistemi ----------------
def default_data():
    return {"money": 0, "owned": ["acemi"], "selected": "acemi", "best_level": 0,
            "best_score": 0, "run": None, "machine": "", "last_ip": "", "levels": {}, "god": False}


def get_machine_id():
    """Bu bilgisayara ozel kimlik (Windows: MachineGuid, macOS: IOPlatformUUID, yoksa MAC + bilgisayar adi)."""
    raw = ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            raw = str(winreg.QueryValueEx(k, "MachineGuid")[0])
    except Exception:
        raw = ""
    if not raw and sys.platform == "darwin":
        try:
            out = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                                 capture_output=True, text=True, timeout=5).stdout
            m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
            raw = m.group(1) if m else ""
        except Exception:
            raw = ""
    if not raw:
        mac = uuid.getnode()
        if mac & (1 << 40):      # rastgele uretilmis MAC ise kullanma (her acilista degisir)
            mac = 0
        raw = f"{mac}-{platform.node()}"
    return hashlib.sha256(("tank-savasi|" + raw).encode("utf-8")).hexdigest()[:24]


def load_game():
    global new_pc_notice
    d = default_data()
    raw = None
    for path in (SAVE_PATH, OLD_SAVE_PATH):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            break
        except (OSError, ValueError):
            continue
    try:
        if isinstance(raw, dict):
            d["money"] = max(0, int(raw.get("money", 0)))
            owned = [t for t in raw.get("owned", []) if t in TANK_BY_ID]
            if "acemi" not in owned:
                owned.append("acemi")
            d["owned"] = owned
            sel = raw.get("selected", "acemi")
            d["selected"] = sel if sel in owned else "acemi"
            d["best_level"] = int(raw.get("best_level", 0))
            d["best_score"] = int(raw.get("best_score", 0))
            d["last_ip"] = str(raw.get("last_ip", ""))[:60]
            lv = raw.get("levels", {})
            if isinstance(lv, dict):
                d["levels"] = {k: max(1, min(MAX_TANK_LEVEL, int(v))) for k, v in lv.items() if k in TANK_BY_ID}
            d["god"] = bool(raw.get("god", False))
            run = raw.get("run")
            if isinstance(run, dict) and run.get("tank") in TANK_BY_ID:
                d["run"] = run
            # Kayit baska bir bilgisayardan geldiyse parayi sifirla
            saved_machine = raw.get("machine")
            if saved_machine and saved_machine != get_machine_id():
                d["money"] = 0
                new_pc_notice = True
    except (TypeError, ValueError):
        pass
    d["machine"] = get_machine_id()
    return d


def save_game():
    global save_error
    try:
        tmp = SAVE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SAVE_PATH)
        save_error = False
    except OSError:
        save_error = True


data = load_game()
if new_pc_notice:
    save_game()


# ---------------- ag (cok oyunculu) ----------------
NET_VERSION = "mp1"
NET_PORT = 5555
SNAP_HZ = 25
INPUT_HZ = 30
MAX_PLAYERS = 4
PLAYER_COLORS = [(255, 220, 80), (90, 220, 255), (255, 130, 210), (150, 255, 120)]
PLAYER_NAME = (os.environ.get("USERNAME") or os.environ.get("USER") or "Oyuncu")[:12]
OWNER_CODES = {"player": 0, "enemy": 1, "boss": 2}
OWNER_NAMES = ["player", "enemy", "boss"]
_eid_counter = itertools.count(1)


def encode(obj):
    return (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")


class NetConn:
    """Satir tabanli JSON mesajlasan TCP baglantisi (ayri thread'lerle calisir, oyunu dondurmaz)."""

    def __init__(self, sock):
        self.sock = sock
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        self.sock.settimeout(None)
        self.inbox = queue.Queue()
        self.outbox = queue.Queue(maxsize=200)
        self.alive = True
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._writer, daemon=True).start()

    def _reader(self):
        buf = b""
        try:
            while self.alive:
                chunk = self.sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line:
                        try:
                            self.inbox.put(json.loads(line))
                        except ValueError:
                            pass
        except OSError:
            pass
        self.alive = False

    def _writer(self):
        try:
            while self.alive:
                try:
                    chunk = self.outbox.get(timeout=0.2)
                except queue.Empty:
                    continue
                self.sock.sendall(chunk)
        except OSError:
            pass
        self.alive = False

    def send_bytes(self, b):
        if not self.alive:
            return
        try:
            self.outbox.put_nowait(b)
        except queue.Full:
            pass    # baglanti cok yavas: paketi atla

    def send(self, obj):
        self.send_bytes(encode(obj))

    def poll(self):
        msgs = []
        while True:
            try:
                msgs.append(self.inbox.get_nowait())
            except queue.Empty:
                break
        return msgs

    def close(self):
        self.alive = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def close_soon(conn, delay=1.0):
    t = threading.Timer(delay, conn.close)
    t.daemon = True
    t.start()


class HostServer:
    def __init__(self):
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("0.0.0.0", NET_PORT))
        self.srv.listen(8)
        self.srv.setblocking(False)
        self.pending = []   # henuz "hello" gondermemis baglantilar
        self.conns = {}     # pid -> NetConn
        self.info = {}      # pid -> {"name":..., "tank":...}
        self.inputs = {}    # pid -> son girdi mesaji

    def accept(self):
        try:
            sock, _addr = self.srv.accept()
        except (BlockingIOError, OSError):
            return
        self.pending.append(NetConn(sock))

    def close(self):
        for c in list(self.conns.values()) + list(self.pending):
            c.close()
        try:
            self.srv.close()
        except OSError:
            pass


def get_local_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    return ips or ["127.0.0.1"]


connect_info = {"status": "idle", "msg": "", "sock": None}


def _connect_worker(h, port):
    try:
        sk = socket.create_connection((h, port), timeout=6)
        connect_info.update(status="ok", sock=sk)
    except OSError:
        connect_info.update(status="error", msg="Bağlanılamadı. IP'yi, host'un odayı açtığını ve "
                                                "güvenlik duvarını kontrol et.")


# ---- efektler (host'ta olusan efektler istemcilere de iletilir) ----
fx_events = []


def fx_sparks(x, y, color, n=5, speed=160, life=0.3):
    spawn_sparks(x, y, color, n, speed, life)
    if len(fx_events) < 300:
        fx_events.append(["sp", int(x), int(y), list(color), n, speed, life])


def fx_explosion(x, y, scale=1.0, scorch=46):
    spawn_explosion(x, y, scale)
    add_scorch(x, y, int(scorch))
    fx_events.append(["x", int(x), int(y), scale, int(scorch)])


def fx_shake(a):
    global shake
    shake = min(1.0, shake + a)
    fx_events.append(["sh", a])


# ---------------- parcaciklar / efektler ----------------
particles = []
popups = []
shake = 0.0
hurt = 0.0


def spawn_sparks(x, y, color, n=5, speed=160, life=0.3):
    for _ in range(n):
        a = random.uniform(0, math.tau)
        sp = random.uniform(0.3, 1.0) * speed
        l = random.uniform(0.6, 1.0) * life
        particles.append([x, y, math.cos(a) * sp, math.sin(a) * sp, l, l, color, random.uniform(2.5, 5)])


def spawn_explosion(x, y, scale=1.0):
    fire = [(255, 230, 110), (255, 160, 50), (240, 85, 30)]
    for _ in range(int(32 * scale)):
        a = random.uniform(0, math.tau)
        sp = random.uniform(40, 340) * scale
        l = random.uniform(0.35, 0.8)
        particles.append([x, y, math.cos(a) * sp, math.sin(a) * sp, l, l,
                          random.choice(fire), random.uniform(5, 12) * scale])
    for _ in range(int(14 * scale)):
        a = random.uniform(0, math.tau)
        sp = random.uniform(10, 130) * scale
        l = random.uniform(0.8, 1.5)
        g = random.randint(55, 100)
        particles.append([x, y, math.cos(a) * sp, math.sin(a) * sp, l, l, (g, g, g),
                          random.uniform(8, 17) * scale])


def update_particles(dt):
    for p in particles:
        p[0] += p[2] * dt
        p[1] += p[3] * dt
        damp = max(0.0, 1 - 3 * dt)
        p[2] *= damp
        p[3] *= damp
        p[4] -= dt
    particles[:] = [p for p in particles if p[4] > 0]
    for q in popups:
        q[1] -= 45 * dt
        q[3] -= dt
    popups[:] = [q for q in popups if q[3] > 0]


def draw_particles(surf):
    for p in particles:
        r = int(p[7] * p[4] / p[5])
        if r >= 1:
            pygame.draw.circle(surf, p[6], (int(p[0]), int(p[1])), r)


# ---------------- arka plan ----------------
def build_background():
    bg = pygame.Surface((W, H))
    bg.fill((62, 98, 56))

    def blotch(color, alpha, rmin, rmax, n):
        for _ in range(n):
            r = random.randint(rmin, rmax)
            s = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(s, (*color, alpha), (r, r), r)
            bg.blit(s, (random.randint(-r, W - r), random.randint(-r, H - r)))

    blotch((84, 126, 72), 26, 80, 200, 40)
    blotch((44, 74, 42), 26, 80, 200, 40)
    blotch((124, 98, 62), 30, 40, 120, 14)
    for _ in range(W * H // 350):
        x, y = random.randint(0, W), random.randint(0, H)
        g = random.randint(-20, 24)
        col = (clamp(62 + g), clamp(98 + g + 6), clamp(56 + g // 2))
        pygame.draw.line(bg, col, (x, y), (x + random.randint(-2, 2), y - random.randint(3, 7)))
    for _ in range(35):
        cx, cy = random.randint(20, W - 20), random.randint(20, H - 20)
        for _ in range(random.randint(1, 3)):
            ball(bg, cx + random.randint(-12, 12), cy + random.randint(-8, 8),
                 random.randint(5, 11), (128, 128, 122))
    return bg


def build_vignette():
    w, h = max(2, W // 6), max(2, H // 6)
    v = pygame.Surface((w, h), pygame.SRCALPHA)
    for yy in range(h):
        for xx in range(w):
            dx = (xx - w / 2) / (w / 2)
            dy = (yy - h / 2) / (h / 2)
            d = math.hypot(dx, dy)
            a = clamp(int(max(0.0, (d - 0.6) / 0.8) * 190), 0, 190)
            v.set_at((xx, yy), (0, 0, 0, a))
    return pygame.transform.smoothscale(v, (W, H))


def add_scorch(x, y, r):
    s = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
    pygame.draw.circle(s, (12, 10, 8, 35), (r, r), r)
    pygame.draw.circle(s, (12, 10, 8, 55), (r, r), int(r * 0.7))
    pygame.draw.circle(s, (12, 10, 8, 70), (r, r), int(r * 0.4))
    background.blit(s, (int(x - r), int(y - r)))


background = build_background()
vignette = build_vignette()
canvas = pygame.Surface((W, H))
hurt_surf = pygame.Surface((W, H), pygame.SRCALPHA)
veil_dark = pygame.Surface((W, H), pygame.SRCALPHA)
veil_dark.fill((0, 0, 0, 150))

# ---------------- mermi ----------------
BULLET_COLORS = {
    "player": (255, 225, 80),
    "enemy": (255, 100, 70),
    "boss": (255, 160, 40),
}
_glow_cache = {}


def get_glow(color):
    if color not in _glow_cache:
        s = pygame.Surface((44, 44), pygame.SRCALPHA)
        for r, a in ((21, 22), (15, 40), (9, 75)):
            pygame.draw.circle(s, (*color, a), (22, 22), r)
        _glow_cache[color] = s
    return _glow_cache[color]


class Bullet:
    def __init__(self, x, y, a, speed, dmg, owner, bounces=0, pid=-1):
        self.x, self.y = x, y
        self.vx, self.vy = math.cos(a) * speed, math.sin(a) * speed
        self.dmg = dmg
        self.owner = owner
        self.pid = pid
        self.bounces = bounces
        self.r = {"player": 6, "boss": 9}.get(owner, 5)
        self.life = 4.0
        self.pierce = 0          # kac dusmanin icinden gecebilir
        self.splash = 0.0        # carpinca cevreye verdigi hasar orani
        self.lifesteal = 0.0     # verdigi hasarin kac kadari can olur
        self.hit_ids = set()
        self.slow = 0
        self.burn = 0
        self.crit = False

    def update(self, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.life -= dt
        hit_wall = False
        if self.x < 0 or self.x > W:
            self.vx *= -1
            self.x = max(0, min(W, self.x))
            hit_wall = True
        if self.y < 0 or self.y > H:
            self.vy *= -1
            self.y = max(0, min(H, self.y))
            hit_wall = True
        if hit_wall:
            fx_sparks(self.x, self.y, BULLET_COLORS[self.owner], 4, 90, 0.2)
            if self.bounces > 0:
                self.bounces -= 1
            else:
                self.life = 0

    def draw(self, surf):
        col = (255, 120, 190) if self.crit else BULLET_COLORS[self.owner]
        surf.blit(get_glow(col), (int(self.x - 22), int(self.y - 22)))
        tail = (self.x - self.vx * 0.025, self.y - self.vy * 0.025)
        pygame.draw.line(surf, shade(col, 0.8), tail, (self.x, self.y), self.r * 2 - 2)
        mid_p = (self.x - self.vx * 0.012, self.y - self.vy * 0.012)
        pygame.draw.line(surf, (255, 255, 235), mid_p, (self.x, self.y), max(2, self.r))


# ---------------- oyuncu ----------------
class Player:
    def __init__(self, tank, pid=0, name="", level=1):
        self.tank = tank
        self.spec = tank["spec"]
        self.r = self.spec["r"]
        self.pid = pid
        self.name = name
        self.x, self.y = W / 2, H / 2
        self.body_a = -math.pi / 2
        self.turret_a = -math.pi / 2
        lv = 1 if tank["id"] == "admin" else max(1, min(MAX_TANK_LEVEL, int(level)))
        self.level = lv
        ls = leveled_stats(tank, lv)
        self.max_hp = ls["hp"]
        self.hp = ls["hp"]
        self.speed = ls["speed"]
        self.cooldown = ls["cooldown"]
        self.timer = 0
        self.dmg = ls["dmg"]
        self.bullet_speed = tank["bullet_speed"]
        self.shots = tank["shots"]
        self.bounces = 0
        self.regen = tank["regen"]
        self.shield = 0
        self.pierce = 0
        self.splash = 0.0
        self.lifesteal = 0.0
        self.shock = 0           # Sok Dalgasi seviyesi
        self.crit = 0.0          # kritik vurus sansi
        self.gold = 0.0          # para bonusu
        self.slow = 0            # yavaslatici mermi seviyesi
        self.burn = 0            # yanici mermi seviyesi
        self.shock_t = 3.0
        for k, v in tank.get("preset", {}).items():     # tanka ozel yetenekler
            setattr(self, k, v)
        self.hp = self.max_hp
        self.recoil = 0.0
        self.flash = 0.0
        self.tread = 0.0
        self.inp = {"dx": 0, "dy": 0, "mx": W / 2, "my": H / 2, "f": False}
        self.opts = []          # bu oyuncuya sunulan yukseltme secenekleri (UPGRADES indeksleri)
        self.picked = False
        self.dead_fx = False
        # istemci tarafinda yumusatma icin hedef degerler
        self.first = True
        self.tx, self.ty = self.x, self.y
        self.tba, self.tta = self.body_a, self.turret_a

    def update(self, dt, inp, bullets):
        dx, dy = inp["dx"], inp["dy"]
        if dx or dy:
            length = math.hypot(dx, dy)
            dx, dy = dx / length, dy / length
            self.x += dx * self.speed * dt
            self.y += dy * self.speed * dt
            self.tread += self.speed * dt
            target = math.atan2(dy, dx)
            d = angle_diff(self.body_a, target)
            self.body_a += max(-8 * dt, min(8 * dt, d))
            if random.random() < 0.25:  # toz
                back = -34 * self.spec["hl"]
                c, sn = math.cos(self.body_a), math.sin(self.body_a)
                lat = random.uniform(-16, 16)
                particles.append([self.x + back * c - lat * sn, self.y + back * sn + lat * c,
                                  0, 0, 0.35, 0.35, (150, 130, 95), random.uniform(3, 6)])
        self.x = max(self.r, min(W - self.r, self.x))
        self.y = max(self.r, min(H - self.r, self.y))

        # kule MOUSE yonune bakar
        self.turret_a = math.atan2(inp["my"] - self.y, inp["mx"] - self.x)

        self.timer -= dt
        self.recoil = max(0.0, self.recoil - 45 * dt)
        self.flash = max(0.0, self.flash - dt)
        if inp["f"] and self.timer <= 0:
            self.timer = self.cooldown
            n = self.shots
            muzzle = self.spec["muzzle"]
            for i in range(n):
                k = i - (n - 1) / 2
                a = self.turret_a + k * 0.12
                perp = self.turret_a + math.pi / 2
                bx = self.x + math.cos(self.turret_a) * muzzle + math.cos(perp) * k * 11
                by = self.y + math.sin(self.turret_a) * muzzle + math.sin(perp) * k * 11
                bl = Bullet(bx, by, a, self.bullet_speed, self.dmg, "player", self.bounces, self.pid)
                bl.pierce, bl.splash, bl.lifesteal = self.pierce, self.splash, self.lifesteal
                bl.slow, bl.burn = self.slow, self.burn
                if self.crit > 0 and random.random() < self.crit:      # Kritik Vurus
                    bl.dmg *= 2
                    bl.crit = True
                    bl.r += 2
                bullets.append(bl)
            self.recoil = 8
            fx_sparks(self.x + math.cos(self.turret_a) * (muzzle + 4),
                      self.y + math.sin(self.turret_a) * (muzzle + 4),
                      (255, 220, 120), 5, 150, 0.2)

        if self.regen > 0:
            self.hp = min(self.max_hp, self.hp + self.regen * dt)

    def hit(self, dmg):
        global shake, hurt
        self.flash = 0.12
        if self.pid == my_pid and god_active():      # GODMODE: olumsuzluk
            return
        if self.shield > 0:
            self.shield -= 1
            fx_sparks(self.x, self.y, (110, 190, 255), 8, 200, 0.3)
            return
        self.hp -= dmg
        fx_events.append(["h", self.pid])
        if self.pid == my_pid:
            hurt = 1.0
            shake = min(1.0, shake + 0.25)

    def draw(self, surf):
        draw_tank(surf, self.x, self.y, self.body_a, self.turret_a, self.spec, 1.0,
                  self.recoil, self.flash / 0.12, self.tread)
        if self.shield > 0:
            pygame.draw.circle(surf, (90, 180, 255), (int(self.x), int(self.y)), 56, 3)
            pygame.draw.circle(surf, (150, 215, 255), (int(self.x), int(self.y)), 52, 1)
        if net_mode != "single":
            col = PLAYER_COLORS[self.pid % len(PLAYER_COLORS)]
            pygame.draw.circle(surf, col, (int(self.x), int(self.y)), int(self.r + 18), 2)
            tag = micro.render(self.name, True, col)
            surf.blit(tag, (int(self.x - tag.get_width() / 2), int(self.y - self.r - 46)))
            w = 54
            bx, by = self.x - w / 2, self.y - self.r - 26
            pygame.draw.rect(surf, (15, 15, 15), (bx - 1, by - 1, w + 2, 9), border_radius=4)
            pygame.draw.rect(surf, col, (bx, by, w * max(0, self.hp) / self.max_hp, 7), border_radius=3)


# ---------------- dusmanlar ----------------
ENEMY_SPECS = [
    make_spec((200, 66, 58), (105, 32, 30), (240, 200, 90)),
    make_spec((226, 138, 40), (120, 72, 20), (60, 60, 60), barrel_len=38),
    make_spec((68, 148, 214), (34, 72, 125), (240, 240, 240), hw=1.1, barrel_len=40),
    make_spec((130, 132, 150), (54, 56, 72), (230, 70, 60), hl=1.05, hw=1.15, tur=1.08,
              barrel_len=44, barrel_w=8),
]
BOSS_SPEC = make_spec((160, 60, 184), (84, 28, 106), (255, 200, 70), hl=1.1, hw=1.15, tur=1.1,
                      barrel_len=40, barrel_w=8, twin=True)


class Enemy:
    def __init__(self, power, boss=False, hp_mult=1.0):
        self.eid = next(_eid_counter)
        self.boss = boss
        self.scale = 2.2 if boss else 1.0
        self.last_pid = -1
        if boss:
            self.tier = -1
            self.spec = BOSS_SPEC
            self.x, self.y = W / 2, -90
            self.max_hp = (300 + power * 50) * hp_mult
            self.speed = min(60 + power, 160)
            self.cooldown = max(1.7 - power * 0.01, 0.8)
            self.dmg = 12 + int(power // 2)
            self.bullet_speed = 420
        else:
            self.tier = min(int(power // 10), len(ENEMY_SPECS) - 1)
            self.spec = ENEMY_SPECS[self.tier]
            side = random.choice("tblr")
            if side == "t":
                self.x, self.y = random.uniform(0, W), -40
            elif side == "b":
                self.x, self.y = random.uniform(0, W), H + 40
            elif side == "l":
                self.x, self.y = -40, random.uniform(0, H)
            else:
                self.x, self.y = W + 40, random.uniform(0, H)
            self.max_hp = (30 + power * 8) * hp_mult
            self.speed = min(70 + power * 3, 200)
            self.cooldown = max(2.4 - power * 0.04, 0.7)
            self.dmg = 8 + int(power // 3)
            self.bullet_speed = min(380 + power * 3, 600)
        self.r = self.spec["r"] * self.scale
        self.hp = self.max_hp
        self.timer = random.uniform(0.5, self.cooldown)
        self.body_a = math.pi / 2
        self.turret_a = math.pi / 2
        self.strafe = random.choice([-1, 1])
        self.recoil = 0.0
        self.flash = 0.0
        self.tread = 0.0
        self.slow_t = 0.0
        self.burn_t = 0.0
        self.burn_dps = 0.0

    def update(self, dt, players, bullets):
        self.slow_t = max(0.0, self.slow_t - dt)
        self.recoil = max(0.0, self.recoil - 40 * dt)
        self.flash = max(0.0, self.flash - dt)
        alive = [p for p in players if p.hp > 0]
        if not alive:
            return
        # en yakin oyuncuyu hedef al
        target_p = min(alive, key=lambda p: (p.x - self.x) ** 2 + (p.y - self.y) ** 2)
        dx, dy = target_p.x - self.x, target_p.y - self.y
        dist = math.hypot(dx, dy) or 1
        ang = math.atan2(dy, dx)
        keep = 420 if self.boss else 320
        if dist > keep:
            mx, my = dx / dist, dy / dist
        else:
            mx, my = -dy / dist * self.strafe, dx / dist * self.strafe
        spd = self.speed * (0.5 if self.slow_t > 0 else 1.0)
        self.x += mx * spd * dt
        self.y += my * spd * dt
        self.tread += spd * dt / self.scale
        target = math.atan2(my, mx)
        self.body_a += max(-4 * dt, min(4 * dt, angle_diff(self.body_a, target)))
        self.turret_a += max(-5 * dt, min(5 * dt, angle_diff(self.turret_a, ang)))
        self.timer -= dt
        if self.timer <= 0:
            self.timer = self.cooldown
            offsets = (-2, -1, 0, 1, 2) if self.boss else (0,)
            owner = "boss" if self.boss else "enemy"
            muzzle = self.spec["muzzle"] * self.scale
            for o in offsets:
                a = self.turret_a + o * 0.2
                bx = self.x + math.cos(a) * muzzle
                by = self.y + math.sin(a) * muzzle
                bullets.append(Bullet(bx, by, a, self.bullet_speed, self.dmg, owner))
            self.recoil = 8
            fx_sparks(self.x + math.cos(self.turret_a) * (muzzle + 4),
                      self.y + math.sin(self.turret_a) * (muzzle + 4),
                      (255, 170, 110), 4, 130, 0.2)

    def draw(self, surf):
        draw_tank(surf, self.x, self.y, self.body_a, self.turret_a, self.spec, self.scale,
                  self.recoil, self.flash / 0.1, self.tread)
        if not self.boss:
            w, h = 58, 7
            bx, by = self.x - w / 2, self.y - self.r - 26
            pygame.draw.rect(surf, (15, 15, 15), (bx - 1, by - 1, w + 2, h + 2), border_radius=4)
            pygame.draw.rect(surf, self.spec["main"], (bx, by, w * max(0, self.hp) / self.max_hp, h),
                             border_radius=3)


# ---------- Yeni ozellikler (her level atlayinca 3 secenek sunulur) ----------
def up_double(p): p.shots += 1
def up_rate(p): p.cooldown *= 0.8
def up_speed(p): p.speed *= 1.12
def up_armor(p): p.max_hp += 30; p.hp = p.max_hp
def up_dmg(p): p.dmg *= 1.3
def up_bounce(p): p.bounces += 1
def up_bspeed(p): p.bullet_speed *= 1.15
def up_regen(p): p.regen += 1.5
def up_shield(p): p.shield += 3
def up_repair(p): p.hp = p.max_hp
def up_sharp(p): p.dmg *= 1.15; p.bullet_speed *= 1.08
def up_iron(p): p.max_hp += 20; p.regen += 0.5
def up_pierce(p): p.pierce += 1
def up_lifesteal(p): p.lifesteal += 0.05
def up_splash(p): p.splash += 0.35
def up_shock(p): p.shock += 1
def up_crit(p): p.crit += 0.10
def up_gold(p): p.gold += 0.25
def up_slow(p): p.slow += 1
def up_burn(p): p.burn += 1


UPGRADES = [
    ("Çok Namlu", "Her atışta +1 mermi (en fazla 5)", up_double, lambda p: p.shots < 5, (255, 200, 70)),
    ("Hızlı Atış", "Atış hızı %25 artar", up_rate, lambda p: p.cooldown > 0.1, (255, 130, 70)),
    ("Turbo Motor", "Tank %12 hızlanır", up_speed, lambda p: p.speed < 520, (90, 200, 255)),
    ("Ağır Zırh", "+30 maksimum can ve tam iyileşme", up_armor, lambda p: True, (110, 220, 120)),
    ("Güçlü Mermi", "Hasar %30 artar", up_dmg, lambda p: True, (240, 80, 80)),
    ("Seken Mermi", "Mermiler duvardan seker (en fazla 4)", up_bounce, lambda p: p.bounces < 4, (200, 140, 255)),
    ("Hızlı Mermi", "Mermi hızı %15 artar", up_bspeed, lambda p: p.bullet_speed < 1200, (255, 240, 130)),
    ("Tamir Kiti", "Saniyede +1.5 can yenilenir", up_regen, lambda p: p.regen < 9, (120, 255, 190)),
    ("Kalkan", "Sonraki 3 hasarı engeller", up_shield, lambda p: p.shield < 9, (130, 190, 255)),
    ("Tam Tamir", "Canını anında doldurur", up_repair, lambda p: p.hp < p.max_hp, (255, 150, 190)),
    ("Keskin Nişan", "Hasar +%15 ve mermi hızı +%8", up_sharp, lambda p: True, (255, 180, 100)),
    ("Demir Deri", "+20 maksimum can ve +0.5 yenilenme", up_iron, lambda p: True, (170, 170, 190)),
    ("Delici Mermi", "Mermiler +1 düşmanın içinden geçer (en fazla 3)", up_pierce,
     lambda p: p.pierce < 3, (120, 255, 120)),
    ("Can Çalma", "Verdiğin hasarın %5'i kadar can kazanırsın (en fazla %40)", up_lifesteal,
     lambda p: p.lifesteal < 0.4, (255, 90, 130)),
    ("Patlayıcı Mermi", "İsabette çevredeki düşmanlara %35 hasar (3 kata kadar birikir)", up_splash,
     lambda p: p.splash < 1.4, (255, 150, 60)),
    ("Şok Dalgası", "Birkaç saniyede bir çevrene elektrik dalgası yayar ve düşmanlara hasar verir (en fazla 4)",
     up_shock, lambda p: p.shock < 4, (110, 200, 255)),
    ("Kritik Vuruş", "%10 ihtimalle 2 kat hasar verirsin (en fazla %50)", up_crit,
     lambda p: p.crit < 0.5, (255, 120, 200)),
    ("Altın Avcısı", "Düşman öldürmekten %25 daha fazla para kazanırsın (en fazla %100)", up_gold,
     lambda p: p.gold < 1.0, (255, 215, 60)),
    ("Yavaşlatıcı Mermi", "Vurduğun düşman bir süre yarı hızda hareket eder (en fazla 3)", up_slow,
     lambda p: p.slow < 3, (150, 170, 255)),
    ("Yanıcı Mermi", "Vurduğun düşman yanar ve 3 saniye boyunca sürekli hasar alır (en fazla 3)", up_burn,
     lambda p: p.burn < 3, (255, 115, 40)),
]


def roll_options(p):
    pool = [i for i, u in enumerate(UPGRADES) if u[3](p)]
    return random.sample(pool, 3)


def apply_pick(p, i):
    if p.picked or not (0 <= i < len(p.opts)):
        return
    UPGRADES[p.opts[i]][2](p)
    p.picked = True


# ---------------- oyun durumu ----------------
state = "menu"          # menu, shop, mp_menu, mp_join, lobby, play, upgrade, over
paused_ui = False       # oyun icindeki ESC menusu
running = True
need_release = False    # tikla basladiktan sonra fare birakilana kadar ates etme
shop_msg = ""
shop_msg_t = 0.0
cursor_visible = None
current_tank_id = data["selected"]
run_money = 0

# ag durumu
net_mode = "single"     # single, host, client
my_pid = 0
host = None
client_conn = None
players = []
player = None
cl_players = {}
cl_enemies = {}
lobby_players = []
net_notice = ""
join_text = data.get("last_ip", "")
code_text = ""
code_msg = ""
code_msg_col = (255, 235, 150)
GOD_MONEY = 1000000


def god_active():
    """GODMODE sadece tek kisilik ve host oyunlarinda calisir (istemcide host belirler)."""
    return bool(data.get("god")) and net_mode != "client"


def apply_code():
    global code_text, code_msg, code_msg_col
    c = code_text.strip().upper()
    if c == "ADMINTANKS":
        if "admin" not in data["owned"]:
            data["owned"].append("admin")
        data["selected"] = "admin"
        code_msg = "ADMIN TANK açıldı ve seçildi! (Dükkanda son sayfada)"
        code_msg_col = (120, 255, 140)
    elif c == "GODMODE":
        data["god"] = not data.get("god", False)
        if data["god"]:
            data["money"] += GOD_MONEY
            code_msg = f"GODMODE AÇIK: +{GOD_MONEY} $ ve ölümsüzlük (tek kişilik / host)"
        else:
            code_msg = "GODMODE KAPALI"
        code_msg_col = (120, 255, 140)
    elif c:
        code_msg = "Geçersiz kod"
        code_msg_col = (255, 110, 100)
    code_text = ""
    save_game()
host_ips = []
lobby_acc = 0.0
net_acc = 0.0
input_acc = 0.0
upgrade_t = 0.0


def get_power():
    # Dusman gucu hem level ile hem de gecen sure ile artar
    return level + elapsed / 25.0


def start_level():
    global kills, kills_needed, spawn_timer, boss_spawned, banner
    kills = 0
    base = min(6 + level // 2, 40)
    kills_needed = int(base * (1 + 0.6 * (max(1, len(players)) - 1)))
    spawn_timer = 0.5
    boss_spawned = False
    banner = 2.5


def reset_game(roster=None):
    global player, players, enemies, bullets, level, state, score, options, elapsed, shake, hurt
    global need_release, run_money, paused_ui, my_pid
    if roster is None:
        my_pid = 0
        roster = [[0, PLAYER_NAME, current_tank_id, tank_level(current_tank_id)]]
    players = []
    n = len(roster)
    for i, row in enumerate(roster):
        pid, name, tid = row[0], row[1], row[2]
        lvl = row[3] if len(row) > 3 else 1
        p = Player(TANK_BY_ID.get(tid, TANK_BY_ID["acemi"]), pid, name, lvl)
        p.x = W / 2 + (i - (n - 1) / 2) * 150
        p.tx = p.x
        players.append(p)
        if pid == my_pid:
            player = p
    enemies, bullets = [], []
    particles.clear()
    popups.clear()
    fx_events.clear()
    level = 1
    state = "play"
    paused_ui = False
    score = 0
    options = []
    elapsed = 0.0
    shake = 0.0
    hurt = 0.0
    run_money = 0
    need_release = True
    start_level()


def snapshot_run():
    if net_mode != "single" or state not in ("play", "upgrade") or player.hp <= 0:
        return None
    return {"tank": current_tank_id, "level": level, "score": score, "elapsed": elapsed,
            "pending": state == "upgrade",
            "stats": {k: getattr(player, k) for k in STAT_KEYS}}


def save_progress():
    """Oyundan cikinca / menuye donunce her seyi kaydeder."""
    if net_mode == "single" and state in ("play", "upgrade") and player is not None and player.hp > 0:
        data["run"] = snapshot_run()
        data["best_score"] = max(data["best_score"], int(score))
        data["best_level"] = max(data["best_level"], level)
    save_game()


def start_new_game():
    global current_tank_id
    leave_net()
    current_tank_id = data["selected"]
    data["run"] = None
    reset_game()


def continue_run():
    global current_tank_id, level, score, elapsed, state, options, need_release
    leave_net()
    run = data["run"]
    try:
        current_tank_id = run["tank"]
        reset_game()
        for k, v in run["stats"].items():
            if k in STAT_KEYS:
                setattr(player, k, v)
        level = int(run["level"])
        score = int(run["score"])
        elapsed = float(run["elapsed"])
        start_level()
        if run.get("pending"):
            player.opts = roll_options(player)
            player.picked = False
            options = [UPGRADES[i] for i in player.opts]
            state = "upgrade"
        else:
            state = "play"
    except (KeyError, TypeError, ValueError):
        data["run"] = None
        start_new_game()
    need_release = True


def go_menu():
    global state, paused_ui
    save_progress()
    leave_net()
    paused_ui = False
    state = "menu"


def quit_game():
    global running
    save_progress()
    leave_net()
    running = False


# ---------------- cok oyunculu: host ----------------
def leave_net():
    global net_mode, host, client_conn
    if host is not None:
        host.close()
        host = None
    if client_conn is not None:
        client_conn.close()
        client_conn = None
    net_mode = "single"
    cl_players.clear()
    cl_enemies.clear()


def start_hosting():
    global net_mode, host, state, my_pid, host_ips, net_notice, current_tank_id
    leave_net()
    try:
        host = HostServer()
    except OSError:
        net_notice = f"Oda açılamadı ({NET_PORT} portu başka bir program tarafından kullanılıyor olabilir)."
        state = "mp_menu"
        return
    net_mode = "host"
    my_pid = 0
    current_tank_id = data["selected"]
    host_ips = get_local_ips()
    net_notice = ""
    state = "lobby"


def lobby_roster():
    r = [[0, PLAYER_NAME, data["selected"], tank_level(data["selected"])]]
    for pid in sorted(host.conns):
        r.append([pid, host.info[pid]["name"], host.info[pid]["tank"], host.info[pid].get("lvl", 1)])
    return r


def handle_hello(conn, m):
    if m.get("ver") != NET_VERSION:
        conn.send({"t": "err", "msg": "Oyun sürümleri farklı. Herkes aynı sürümü kullanmalı."})
        close_soon(conn)
        return
    free = [i for i in range(1, MAX_PLAYERS) if i not in host.conns]
    if state != "lobby" or not free:
        conn.send({"t": "err", "msg": "Oda dolu ya da oyun çoktan başlamış."})
        close_soon(conn)
        return
    pid = free[0]
    tank = m.get("tank")
    host.conns[pid] = conn
    try:
        lvl = max(1, min(MAX_TANK_LEVEL, int(m.get("lvl", 1))))
    except (TypeError, ValueError):
        lvl = 1
    host.info[pid] = {"name": str(m.get("name", "Oyuncu"))[:12],
                      "tank": tank if tank in TANK_BY_ID else "acemi", "lvl": lvl}
    conn.send({"t": "welcome", "pid": pid})


def drop_client(pid):
    conn = host.conns.pop(pid, None)
    host.info.pop(pid, None)
    host.inputs.pop(pid, None)
    if conn is not None:
        conn.close()
    players[:] = [p for p in players if p.pid != pid]


def set_remote_input(p, m):
    try:
        p.inp = {"dx": clamp(float(m.get("dx", 0)), -1, 1), "dy": clamp(float(m.get("dy", 0)), -1, 1),
                 "mx": float(m.get("mx", p.x)), "my": float(m.get("my", p.y)), "f": bool(m.get("f"))}
    except (TypeError, ValueError):
        pass


def host_service(dt):
    global lobby_acc
    for _ in range(4):
        host.accept()
    for conn in list(host.pending):
        got = False
        for m in conn.poll():
            if m.get("t") == "hello":
                host.pending.remove(conn)
                handle_hello(conn, m)
                got = True
                break
        if not got and not conn.alive:
            host.pending.remove(conn)
    for pid, conn in list(host.conns.items()):
        for m in conn.poll():
            t = m.get("t")
            if t == "in":
                host.inputs[pid] = m
            elif t == "pick" and state == "upgrade":
                p = next((q for q in players if q.pid == pid), None)
                if p is not None:
                    try:
                        apply_pick(p, int(m.get("i", -1)))
                    except (TypeError, ValueError):
                        pass
        if not conn.alive:
            drop_client(pid)
    if state == "lobby":
        lobby_acc += dt
        if lobby_acc >= 0.5:
            lobby_acc = 0.0
            msg = {"t": "lobby", "players": lobby_roster()}
            for conn in host.conns.values():
                conn.send(msg)


def host_start_game():
    global current_tank_id
    current_tank_id = data["selected"]
    roster = lobby_roster()
    reset_game(roster)
    for conn in host.conns.values():
        conn.send({"t": "start", "roster": roster})


def host_send_options():
    for pid, conn in host.conns.items():
        p = next((q for q in players if q.pid == pid), None)
        if p is not None:
            conn.send({"t": "opt", "o": p.opts})


def host_send_snapshot():
    if host is None or not host.conns:
        fx_events.clear()
        return
    rows_p = [[p.pid, int(p.x), int(p.y), round(p.body_a, 2), round(p.turret_a, 2),
               round(p.recoil, 1), round(p.flash, 2), int(p.tread)]
              + [round(getattr(p, k), 2) for k in STAT_KEYS] for p in players]
    rows_e = [[en.eid, int(en.x), int(en.y), round(en.body_a, 2), round(en.turret_a, 2),
               int(en.hp), int(en.max_hp), 1 if en.boss else 0, en.tier,
               round(en.recoil, 1), round(en.flash, 2), int(en.tread)] for en in enemies]
    rows_b = [[int(b.x), int(b.y), int(b.vx), int(b.vy), OWNER_CODES[b.owner]] for b in bullets]
    msg = {"t": "s", "st": state, "lv": level, "k": kills, "kn": kills_needed, "el": round(elapsed, 1),
           "sc": score, "bn": round(banner, 1), "ut": int(upgrade_t),
           "p": rows_p, "e": rows_e, "b": rows_b, "ev": fx_events[:]}
    fx_events.clear()
    line = encode(msg)
    for conn in host.conns.values():
        if conn.outbox.qsize() < 8:
            conn.send_bytes(line)


# ---------------- cok oyunculu: istemci ----------------
def start_join():
    global net_notice
    text = join_text.strip()
    if not text:
        net_notice = "Önce host'un IP adresini yaz."
        return
    h, port = text, NET_PORT
    if ":" in text:
        hh, _, pt = text.rpartition(":")
        try:
            h, port = hh, int(pt)
        except ValueError:
            net_notice = "Port numarası hatalı."
            return
    if connect_info["status"] == "connecting":
        return
    connect_info.update(status="connecting", msg="", sock=None)
    net_notice = ""
    data["last_ip"] = text
    threading.Thread(target=_connect_worker, args=(h, port), daemon=True).start()


def check_connect():
    global client_conn, net_mode, state, net_notice
    if connect_info["status"] == "ok":
        sock = connect_info["sock"]
        connect_info.update(status="idle", sock=None)
        client_conn = NetConn(sock)
        net_mode = "client"
        client_conn.send({"t": "hello", "name": PLAYER_NAME, "tank": data["selected"], "ver": NET_VERSION,
                          "lvl": tank_level(data["selected"])})
        lobby_players[:] = []
        net_notice = ""
        state = "lobby"
        save_game()
    elif connect_info["status"] == "error":
        net_notice = connect_info["msg"]
        connect_info["status"] = "idle"


def client_service():
    global state, net_notice, my_pid
    for m in client_conn.poll():
        t = m.get("t")
        if t == "welcome":
            my_pid = int(m.get("pid", 1))
        elif t == "err":
            net_notice = str(m.get("msg", "Hata"))
            leave_net()
            state = "mp_menu"
            return
        elif t == "lobby":
            lobby_players[:] = m.get("players", [])
        elif t == "start":
            begin_client_game(m.get("roster", []))
        elif t == "opt":
            set_client_options(m.get("o", []))
        elif t == "s":
            apply_snapshot(m)
    if client_conn is not None and not client_conn.alive:
        net_notice = "Bağlantı koptu."
        leave_net()
        state = "mp_menu"


def set_client_options(idx):
    global options
    options = [UPGRADES[i] for i in idx if 0 <= i < len(UPGRADES)]
    if player is not None:
        player.picked = False


def begin_client_game(roster):
    global players, player, enemies, bullets, level, state, score, elapsed, run_money, banner, options
    global kills, kills_needed, paused_ui, need_release, shake, hurt, upgrade_t
    cl_players.clear()
    cl_enemies.clear()
    for row in roster:
        pid, name, tid = row[0], row[1], row[2]
        lvl = row[3] if len(row) > 3 else 1
        cl_players[pid] = Player(TANK_BY_ID.get(tid, TANK_BY_ID["acemi"]), pid, name, lvl)
    players = list(cl_players.values())
    player = cl_players.get(my_pid) or players[0]
    enemies, bullets = [], []
    particles.clear()
    popups.clear()
    level, kills, kills_needed, score, elapsed = 1, 0, 6, 0, 0.0
    run_money = 0
    banner = 2.5
    options = []
    state = "play"
    paused_ui = False
    need_release = True
    shake = hurt = 0.0
    upgrade_t = 0.0


def make_remote_enemy(row):
    en = Enemy.__new__(Enemy)
    en.eid = row[0]
    en.boss = bool(row[7])
    en.scale = 2.2 if en.boss else 1.0
    en.spec = BOSS_SPEC if en.boss else ENEMY_SPECS[max(0, min(row[8], len(ENEMY_SPECS) - 1))]
    en.r = en.spec["r"] * en.scale
    en.x, en.y, en.body_a, en.turret_a = row[1], row[2], row[3], row[4]
    en.tx, en.ty, en.tba, en.tta = en.x, en.y, en.body_a, en.turret_a
    en.hp, en.max_hp = row[5], max(1, row[6])
    en.recoil, en.flash, en.tread = row[9], row[10], row[11]
    return en


def apply_snapshot(m):
    global state, level, kills, kills_needed, elapsed, score, banner, enemies, bullets
    global need_release, shake, hurt, upgrade_t, run_money
    st = m.get("st")
    if st == "upgrade" and state == "play":
        state = "upgrade"
        save_game()
    elif st == "play" and state == "upgrade":
        state = "play"
        need_release = True
    elif st == "over" and state != "over":
        state = "over"
        data["best_score"] = max(data["best_score"], int(m.get("sc", 0)))
        data["best_level"] = max(data["best_level"], int(m.get("lv", 0)))
        save_game()
    level = m.get("lv", level)
    kills = m.get("k", kills)
    kills_needed = m.get("kn", kills_needed)
    elapsed = m.get("el", elapsed)
    score = m.get("sc", score)
    banner = m.get("bn", banner)
    upgrade_t = m.get("ut", 0)

    for row in m.get("p", []):
        p = cl_players.get(row[0])
        if p is None:
            continue
        p.tx, p.ty, p.tba, p.tta = row[1], row[2], row[3], row[4]
        if p.first:
            p.x, p.y, p.body_a, p.turret_a = p.tx, p.ty, p.tba, p.tta
            p.first = False
        p.recoil, p.flash, p.tread = row[5], row[6], row[7]
        for k, v in zip(STAT_KEYS, row[8:]):
            setattr(p, k, v)

    seen = set()
    for row in m.get("e", []):
        seen.add(row[0])
        en = cl_enemies.get(row[0])
        if en is None:
            en = make_remote_enemy(row)
            cl_enemies[row[0]] = en
        en.tx, en.ty, en.tba, en.tta = row[1], row[2], row[3], row[4]
        en.hp, en.max_hp = row[5], max(1, row[6])
        en.recoil, en.flash, en.tread = row[9], row[10], row[11]
    for eid in list(cl_enemies):
        if eid not in seen:
            del cl_enemies[eid]
    enemies = list(cl_enemies.values())

    bl = []
    for x, y, vx, vy, o in m.get("b", []):
        b = Bullet(x, y, 0, 0, 0, OWNER_NAMES[o if 0 <= o < 3 else 0])
        b.vx, b.vy = vx, vy
        bl.append(b)
    bullets = bl

    for ev in m.get("ev", []):
        k = ev[0]
        if k == "x":
            spawn_explosion(ev[1], ev[2], ev[3])
            add_scorch(ev[1], ev[2], ev[4])
        elif k == "sp":
            spawn_sparks(ev[1], ev[2], tuple(ev[3]), ev[4], ev[5], ev[6])
        elif k == "sh":
            shake = min(1.0, shake + ev[1])
        elif k == "h":
            if ev[1] == my_pid:
                hurt = 1.0
                shake = min(1.0, shake + 0.25)
        elif k == "$":
            if ev[1] == my_pid:
                data["money"] += ev[2]
                run_money += ev[2]
                popups.append([ev[3], ev[4], f"+{ev[2]} $", 1.3])


def client_update(dt):
    """Istemcide goruntuyu yumusatir; mermileri hizlariyla ilerletir."""
    global banner
    k = min(1.0, 14 * dt)
    for p in cl_players.values():
        p.x += (p.tx - p.x) * k
        p.y += (p.ty - p.y) * k
        p.body_a += angle_diff(p.body_a, p.tba) * k
        p.turret_a += angle_diff(p.turret_a, p.tta) * k
    if player is not None and player.hp > 0 and state == "play" and not paused_ui:
        player.turret_a = math.atan2(mouse_pos[1] - player.y, mouse_pos[0] - player.x)
    for en in cl_enemies.values():
        en.x += (en.tx - en.x) * k
        en.y += (en.ty - en.y) * k
        en.body_a += angle_diff(en.body_a, en.tba) * k
        en.turret_a += angle_diff(en.turret_a, en.tta) * k
    for b in bullets:
        b.x += b.vx * dt
        b.y += b.vy * dt
    banner = max(0, banner - dt)


def client_send_input(inp):
    client_conn.send({"t": "in", "dx": inp["dx"], "dy": inp["dy"], "mx": int(inp["mx"]),
                      "my": int(inp["my"]), "f": 1 if inp["f"] else 0})


# Android icin iki sanal joystick: sol hareket, sag nisangah + surekli ates.
TOUCH_MOVE_CENTER = (165, H - 165)
TOUCH_AIM_CENTER = (W - 165, H - 165)
TOUCH_STICK_RADIUS = 100
touch_move_id = None
touch_move_pos = TOUCH_MOVE_CENTER
touch_aim_id = None
touch_aim_pos = TOUCH_AIM_CENTER
touch_aim_angle = -math.pi / 2


def local_input(keys):
    global touch_aim_angle
    if paused_ui:
        return {"dx": 0, "dy": 0, "mx": mouse_pos[0], "my": mouse_pos[1], "f": False}

    dx = int(bool(keys[pygame.K_d] or keys[pygame.K_RIGHT])) - int(bool(keys[pygame.K_a] or keys[pygame.K_LEFT]))
    dy = int(bool(keys[pygame.K_s] or keys[pygame.K_DOWN])) - int(bool(keys[pygame.K_w] or keys[pygame.K_UP]))
    mx, my = mouse_pos

    if ANDROID and touch_move_id is not None:
        vx = (touch_move_pos[0] - TOUCH_MOVE_CENTER[0]) / TOUCH_STICK_RADIUS
        vy = (touch_move_pos[1] - TOUCH_MOVE_CENTER[1]) / TOUCH_STICK_RADIUS
        length = math.hypot(vx, vy)
        if length < 0.12:
            dx, dy = 0, 0
        else:
            if length > 1:
                vx, vy = vx / length, vy / length
            dx, dy = vx, vy

    if ANDROID and touch_aim_id is not None:
        ax = touch_aim_pos[0] - TOUCH_AIM_CENTER[0]
        ay = touch_aim_pos[1] - TOUCH_AIM_CENTER[1]
        if math.hypot(ax, ay) > 12:
            touch_aim_angle = math.atan2(ay, ax)
        # Oyuncunun konumundan bakis acisi yonunde sanal imlec noktasi.
        if player is not None:
            mx = player.x + math.cos(touch_aim_angle) * 600
            my = player.y + math.sin(touch_aim_angle) * 600

    if ANDROID:
        firing = (touch_aim_id is not None) or bool(keys[pygame.K_SPACE])
    else:
        firing = (mouse_down and not need_release) or bool(keys[pygame.K_SPACE])
    return {"dx": dx, "dy": dy, "mx": mx, "my": my, "f": firing}


def do_action(act):
    global state, need_release, paused_ui, net_notice, shop_page, code_text, code_msg
    if act == "continue":
        continue_run()
    elif act == "new":
        start_new_game()
    elif act == "shop":
        state = "shop"
        shop_page = 0
    elif act == "code":
        code_text = ""
        code_msg = ""
        state = "code"
    elif act == "do_code":
        apply_code()
    elif act == "menu":
        go_menu()
    elif act == "quit":
        quit_game()
    elif act == "resume":
        paused_ui = False
        need_release = True
    elif act == "mp":
        leave_net()
        net_notice = ""
        state = "mp_menu"
    elif act == "host":
        start_hosting()
    elif act == "join":
        net_notice = ""
        connect_info.update(status="idle", msg="", sock=None)
        state = "mp_join"
    elif act == "do_join":
        start_join()
    elif act in ("mp_start", "restart_mp"):
        host_start_game()
    elif act == "leave":
        leave_net()
        state = "mp_menu"


# ---------------- arayuz yardimcilari ----------------
def draw_text(text, f, color, center, shadow=True):
    img = f.render(text, True, color)
    if shadow:
        sh = f.render(text, True, (0, 0, 0))
        screen.blit(sh, sh.get_rect(center=(center[0] + 3, center[1] + 3)))
    screen.blit(img, img.get_rect(center=center))


def wrap_text(text, f, max_w):
    lines, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if f.size(t)[0] <= max_w:
            cur = t
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def panel(rect, alpha=140):
    rect = tuple(int(v) for v in rect)
    s = pygame.Surface((rect[2], rect[3]), pygame.SRCALPHA)
    pygame.draw.rect(s, (10, 14, 12, alpha), (0, 0, rect[2], rect[3]), border_radius=12)
    pygame.draw.rect(s, (255, 255, 255, 60), (0, 0, rect[2], rect[3]), 2, border_radius=12)
    screen.blit(s, (rect[0], rect[1]))


def draw_button(rect, label, hover, enabled=True, color=(56, 108, 70)):
    base = color if enabled else (62, 62, 62)
    fill = shade(base, 1.3) if (hover and enabled) else base
    pygame.draw.rect(screen, shade(fill, 0.45), rect.move(0, 4), border_radius=14)
    pygame.draw.rect(screen, fill, rect, border_radius=14)
    pygame.draw.rect(screen, shade(fill, 1.7), rect, 2, border_radius=14)
    draw_text(label, mid, (255, 255, 255) if enabled else (150, 150, 150), rect.center)


def stack_buttons(labels, y0):
    bw, bh, gap = 440, 62, 16
    x = (W - bw) // 2
    return [(lab, act, pygame.Rect(x, y0 + i * (bh + gap), bw, bh)) for i, (lab, act) in enumerate(labels)]


def menu_buttons():
    labels = []
    if data["run"]:
        labels.append((f"Devam Et (Level {data['run']['level']})", "continue"))
    labels += [("Yeni Oyun (Tek Kişilik)", "new"), ("Çok Oyunculu", "mp"), ("Dükkan", "shop"),
               ("Kod Gir", "code"), ("Çıkış", "quit")]
    return stack_buttons(labels, int(H * 0.46))


def pause_buttons():
    if net_mode == "single":
        return stack_buttons([("Devam Et", "resume"), ("Kaydet ve Menüye Dön", "menu"),
                              ("Kaydet ve Çık", "quit")], H // 2 - 60)
    return stack_buttons([("Devam Et", "resume"), ("Oyundan Ayrıl", "menu"), ("Kaydet ve Çık", "quit")],
                         H // 2 - 60)


def over_buttons():
    if net_mode == "single":
        return stack_buttons([("Tekrar Oyna", "new"), ("Dükkan", "shop"), ("Ana Menü", "menu")],
                             H // 2 + 130)
    if net_mode == "host":
        return stack_buttons([("Tekrar Oyna", "restart_mp"), ("Ana Menü", "menu")], H // 2 + 130)
    return stack_buttons([("Ana Menü", "menu")], H // 2 + 130)


def code_buttons():
    return stack_buttons([("Uygula", "do_code"), ("Geri", "menu")], int(H * 0.58))


def mp_menu_buttons():
    return stack_buttons([("Oda Kur (Host)", "host"), ("Odaya Katıl", "join"), ("Geri", "menu")],
                         int(H * 0.52))


def join_buttons():
    return stack_buttons([("Bağlan", "do_join"), ("Geri", "mp")], int(H * 0.58))


def lobby_buttons():
    if net_mode == "host":
        return stack_buttons([("Oyunu Başlat", "mp_start"), ("Odayı Kapat", "leave")], int(H * 0.72))
    return stack_buttons([("Odadan Ayrıl", "leave")], int(H * 0.72))


def current_buttons():
    if state == "menu":
        return menu_buttons()
    if state == "play" and paused_ui:
        return pause_buttons()
    if state == "over":
        return over_buttons()
    if state == "mp_menu":
        return mp_menu_buttons()
    if state == "code":
        return code_buttons()
    if state == "mp_join":
        return join_buttons()
    if state == "lobby":
        return lobby_buttons()
    return []


def option_rects():
    bw, bh = 340, 280
    gap = 40
    total = 3 * bw + 2 * gap
    x0 = (W - total) // 2
    return [pygame.Rect(x0 + i * (bw + gap), H // 2 - bh // 2 + 30, bw, bh) for i in range(3)]


def choose(i):
    global need_release
    if player is None or player.picked or not (0 <= i < len(options)):
        return
    if net_mode == "client":
        client_conn.send({"t": "pick", "i": i})
        player.picked = True
    else:
        apply_pick(player, i)
    need_release = True


def fmt_time(t):
    return f"{int(t) // 60:02d}:{int(t) % 60:02d}"


# ---------------- dukkan ----------------
SHOP_PAGE_SIZE = 8
shop_page = 0


def tank_level(tid):
    try:
        return max(1, min(MAX_TANK_LEVEL, int(data["levels"].get(tid, 1))))
    except (TypeError, ValueError):
        return 1


def upgrade_cost(t, lvl):
    return int(max(300, t["price"]) * 0.5 * lvl)


def leveled_stats(t, lvl):
    """Tank seviyesine gore temel degerler: her seviye +%10 can, +%8 hasar, +%3 hiz, -%3 atis suresi."""
    k = lvl - 1
    return {"hp": t["hp"] * (1 + 0.10 * k), "dmg": t["dmg"] * (1 + 0.08 * k),
            "speed": t["speed"] * (1 + 0.03 * k), "cooldown": t["cooldown"] * (0.97 ** k)}


def shop_tanks():
    lst = list(TANKS)
    if "admin" in data["owned"]:
        lst.append(ADMIN_TANK)
    return lst


def shop_page_count():
    return max(1, (len(shop_tanks()) + SHOP_PAGE_SIZE - 1) // SHOP_PAGE_SIZE)


def shop_layout():
    cols = 4
    gap = 20
    cw = min(360, (W - 80 - gap * (cols - 1)) // cols)
    avail = H - 130 - 90
    ch = max(270, min(380, (avail - gap) // 2))
    total_w = cols * cw + gap * (cols - 1)
    x0 = (W - total_w) // 2
    tanks = shop_tanks()[shop_page * SHOP_PAGE_SIZE:(shop_page + 1) * SHOP_PAGE_SIZE]
    rects = []
    for i in range(len(tanks)):
        row, col = divmod(i, cols)
        rects.append(pygame.Rect(x0 + col * (cw + gap), 125 + row * (ch + gap), cw, ch))
    back = pygame.Rect(W // 2 - 120, H - 68, 240, 52)
    prev_b = pygame.Rect(W // 2 - 460, H - 68, 170, 52)
    next_b = pygame.Rect(W // 2 + 290, H - 68, 170, 52)
    return rects, back, prev_b, next_b, tanks


def shop_card_buttons(r, owned):
    y, h = r.bottom - 44, 32
    if owned:
        main = pygame.Rect(r.x + 16, y, int((r.width - 40) * 0.5), h)
        up = pygame.Rect(main.right + 8, y, r.width - 32 - main.width - 8, h)
        return main, up
    return pygame.Rect(r.x + 16, y, r.width - 32, h), None


def shop_action(t, which):
    global shop_msg, shop_msg_t
    owned = t["id"] in data["owned"]
    if which == "up" and owned:
        lvl = tank_level(t["id"])
        if t["id"] == "admin" or lvl >= MAX_TANK_LEVEL:
            shop_msg = f"{t['name']} zaten en yüksek seviyede"
        else:
            cost = upgrade_cost(t, lvl)
            if data["money"] >= cost:
                data["money"] -= cost
                data["levels"][t["id"]] = lvl + 1
                shop_msg = f"{t['name']} seviye {lvl + 1} oldu!"
                save_game()
            else:
                shop_msg = f"Yetersiz para! {cost - data['money']} $ daha lazım"
    elif owned:
        data["selected"] = t["id"]
        shop_msg = f"{t['name']} seçildi (yeni oyunda kullanılır)"
        save_game()
    elif data["money"] >= t["price"]:
        data["money"] -= t["price"]
        data["owned"].append(t["id"])
        data["selected"] = t["id"]
        shop_msg = f"{t['name']} satın alındı!"
        save_game()
    else:
        shop_msg = f"Yetersiz para! {t['price'] - data['money']} $ daha lazım"
    shop_msg_t = 2.5


def draw_bar(x, y, w, frac, color):
    pygame.draw.rect(screen, (30, 34, 32), (x, y, w, 8), border_radius=4)
    pygame.draw.rect(screen, color, (x, y, max(3, w * clamp(frac, 0, 1)), 8), border_radius=4)


def draw_small_button(rect, label, color):
    fill = shade(color, 1.25) if rect.collidepoint(mouse_pos) else color
    pygame.draw.rect(screen, fill, rect, border_radius=10)
    pygame.draw.rect(screen, shade(fill, 1.6), rect, 2, border_radius=10)
    draw_text(label, micro, (255, 255, 255), rect.center, shadow=False)


def draw_shop():
    screen.blit(background, (0, 0))
    screen.blit(veil_dark, (0, 0))
    screen.blit(vignette, (0, 0))
    draw_text("DÜKKAN", big, (255, 235, 150), (W // 2, 52))
    draw_text(f"Para: {data['money']} $", mid, (255, 215, 80), (W - 190, 52))
    rects, back, prev_b, next_b, tanks = shop_layout()
    t_now = pygame.time.get_ticks() / 1000
    for i, (r, tk) in enumerate(zip(rects, tanks)):
        owned = tk["id"] in data["owned"]
        selected = data["selected"] == tk["id"]
        is_admin = tk["id"] == "admin"
        lv = 1 if is_admin else tank_level(tk["id"])
        ls = leveled_stats(tk, lv)
        hover = r.collidepoint(mouse_pos)
        fill = (44, 66, 50) if hover else (28, 40, 32)
        pygame.draw.rect(screen, fill, r, border_radius=16)
        border = (255, 215, 80) if selected else (110, 220, 130) if owned else (120, 125, 130)
        pygame.draw.rect(screen, border, r, 4 if selected else 2, border_radius=16)

        sc = 0.85 + (r.height - 270) / 250
        cx, cy = r.centerx, r.y + int(r.height * 0.22)
        ta = math.atan2(mouse_pos[1] - cy, mouse_pos[0] - cx)
        draw_tank(screen, cx, cy, -0.4 + math.sin(t_now * 0.7 + i) * 0.25, ta, tk["spec"], sc,
                  0, 0, t_now * 25)

        title = tk["name"] + (f"  Sv.{lv}" if owned and not is_admin else "")
        draw_text(title, name_font, (255, 255, 255), (r.centerx, r.y + int(r.height * 0.45)))
        draw_text(tk["desc"], micro, (200, 215, 200), (r.centerx, r.y + int(r.height * 0.53)), shadow=False)

        stats = [("Can", ls["hp"] / 450, (110, 220, 120)),
                 ("Hız", ls["speed"] / 420, (90, 200, 255)),
                 ("Hasar", ls["dmg"] / 110, (240, 90, 80)),
                 ("Atış", (1 / ls["cooldown"]) / 5.0, (255, 200, 70))]
        sy = r.y + int(r.height * 0.60)
        for k, (lab, frac, col) in enumerate(stats):
            yy = sy + k * 15
            screen.blit(micro.render(lab, True, (220, 225, 220)), (r.x + 16, yy - 3))
            draw_bar(r.x + 74, yy, r.width - 94, frac, col)

        main_btn, up_btn = shop_card_buttons(r, owned)
        if selected:
            label, bcol = "SEÇİLİ", (160, 130, 30)
        elif owned:
            label, bcol = "KULLAN", (56, 108, 70)
        elif data["money"] >= tk["price"]:
            label, bcol = f"SATIN AL  {tk['price']} $", (40, 120, 150)
        else:
            label, bcol = f"{tk['price']} $", (110, 60, 60)
        if owned:
            draw_small_button(main_btn, label, bcol)
        else:
            bfill = shade(bcol, 1.25) if main_btn.collidepoint(mouse_pos) else bcol
            pygame.draw.rect(screen, bfill, main_btn, border_radius=10)
            pygame.draw.rect(screen, shade(bfill, 1.6), main_btn, 2, border_radius=10)
            draw_text(label, tiny, (255, 255, 255), main_btn.center, shadow=False)
        if up_btn is not None:
            if is_admin or lv >= MAX_TANK_LEVEL:
                draw_small_button(up_btn, "MAKS", (90, 90, 96))
            else:
                cost = upgrade_cost(tk, lv)
                afford = data["money"] >= cost
                draw_small_button(up_btn, f"Yükselt {cost} $", (150, 100, 30) if afford else (100, 60, 60))

    pages = shop_page_count()
    if pages > 1:
        draw_text(f"Sayfa {shop_page + 1} / {pages}", tiny, (230, 230, 230), (W // 2, H - 92))
        draw_button(prev_b, "Önceki", prev_b.collidepoint(mouse_pos), color=(60, 80, 110))
        draw_button(next_b, "Sonraki", next_b.collidepoint(mouse_pos), color=(60, 80, 110))
    draw_button(back, "Geri", back.collidepoint(mouse_pos))
    if shop_msg_t > 0:
        draw_text(shop_msg, tiny, (255, 235, 150), (W // 2, 108))


def draw_menu():
    screen.blit(background, (0, 0))
    screen.blit(veil_dark, (0, 0))
    screen.blit(vignette, (0, 0))
    draw_text("TANK SAVAŞI", big, (255, 235, 150), (W // 2, int(H * 0.12)))
    tk = TANK_BY_ID[data["selected"]]
    cx, cy = W // 2, int(H * 0.32)
    t_now = pygame.time.get_ticks() / 1000
    ta = math.atan2(mouse_pos[1] - cy, mouse_pos[0] - cx)
    draw_tank(screen, cx, cy, -0.35 + math.sin(t_now * 0.6) * 0.2, ta, tk["spec"], 2.4, 0, 0, t_now * 30)
    draw_text(tk["name"], mid, (255, 255, 255), (W // 2, cy + 98))
    panel((W - 330, 14, 316, 100))
    screen.blit(font.render(f"Para: {data['money']} $", True, (255, 215, 80)), (W - 316, 24))
    screen.blit(small.render(f"En iyi level: {data['best_level']}", True, (230, 230, 230)), (W - 316, 56))
    screen.blit(small.render(f"En yüksek skor: {data['best_score']}", True, (230, 230, 230)), (W - 316, 80))
    for lab, act, r in menu_buttons():
        draw_button(r, lab, r.collidepoint(mouse_pos), color=(56, 108, 70) if act != "quit" else (110, 60, 60))
    draw_text("WASD: hareket   Mouse: nişan   Sol tık: ateş   ESC: menü", small, (225, 225, 225),
              (W // 2, H - 30), shadow=False)
    if new_pc_notice:
        draw_text("Yeni bilgisayar algılandı: paran sıfırlandı", tiny, (255, 200, 90), (W // 2, H - 92))
    if save_error:
        draw_text("Kayıt dosyası yazılamadı!", tiny, (255, 90, 90), (W // 2, H - 62))
    draw_text(f"Kayıt: {SAVE_PATH}", micro, (185, 185, 185), (W // 2, H - 10), shadow=False)


def draw_backdrop():
    screen.blit(background, (0, 0))
    screen.blit(veil_dark, (0, 0))
    screen.blit(vignette, (0, 0))


def draw_touch_controls():
    """Android yatay ekraninda iki sanal joystick cizer."""
    lx, ly = TOUCH_MOVE_CENTER
    rx, ry = TOUCH_AIM_CENTER
    radius = TOUCH_STICK_RADIUS

    pygame.draw.circle(screen, (23, 31, 31), (lx, ly), radius)
    pygame.draw.circle(screen, (108, 135, 124), (lx, ly), radius, 4)
    pygame.draw.circle(screen, (63, 83, 76), (lx, ly), 48, 2)
    move_knob = touch_move_pos if touch_move_id is not None else TOUCH_MOVE_CENTER
    pygame.draw.circle(screen, (57, 110, 91), (int(move_knob[0]), int(move_knob[1])), 35)
    pygame.draw.circle(screen, (195, 225, 207), (int(move_knob[0]), int(move_knob[1])), 35, 3)

    pygame.draw.circle(screen, (23, 31, 31), (rx, ry), radius)
    pygame.draw.circle(screen, (126, 118, 83), (rx, ry), radius, 4)
    pygame.draw.circle(screen, (83, 73, 51), (rx, ry), 48, 2)
    aim_knob = touch_aim_pos if touch_aim_id is not None else TOUCH_AIM_CENTER
    pygame.draw.circle(screen, (143, 99, 43), (int(aim_knob[0]), int(aim_knob[1])), 35)
    pygame.draw.circle(screen, (255, 222, 150), (int(aim_knob[0]), int(aim_knob[1])), 35, 3)

    label_l = micro.render("HAREKET", True, (235, 245, 235))
    label_r = micro.render("NISAN + ATES", True, (255, 235, 190))
    screen.blit(label_l, (lx - label_l.get_width() // 2, ly - radius - 27))
    screen.blit(label_r, (rx - label_r.get_width() // 2, ry - radius - 27))


def draw_code():
    draw_backdrop()
    draw_text("KOD BÖLÜMÜ", big, (255, 235, 150), (W // 2, int(H * 0.14)))
    draw_text("Gizli kodu yaz ve Enter'a bas", mid, (230, 235, 230), (W // 2, int(H * 0.28)), shadow=False)
    box = pygame.Rect(W // 2 - 300, int(H * 0.36), 600, 70)
    pygame.draw.rect(screen, (20, 28, 22), box, border_radius=14)
    pygame.draw.rect(screen, (190, 240, 200), box, 3, border_radius=14)
    caret = "|" if (pygame.time.get_ticks() // 500) % 2 == 0 else " "
    draw_text(code_text + caret, mid, (255, 255, 255), box.center, shadow=False)
    if code_msg:
        draw_text(code_msg, tiny, code_msg_col, (W // 2, int(H * 0.50)))
    for lab, act, r in code_buttons():
        draw_button(r, lab, r.collidepoint(mouse_pos), color=(56, 108, 70) if act != "menu" else (110, 60, 60))


def draw_mp_menu():
    draw_backdrop()
    draw_text("ÇOK OYUNCULU", big, (255, 235, 150), (W // 2, int(H * 0.14)))
    lines = ["Arkadaşlarınla birlikte düşman dalgalarına karşı savaş (en fazla 4 oyuncu).",
             "Aynı Wi-Fi / ağdaysanız: host'un yerel IP adresini yazmanız yeterli.",
             "Farklı evlerdeyseniz: hepiniz Radmin VPN, ZeroTier veya Tailscale kurup",
             "host'un o programdaki IP adresini kullanın (ya da host modemde "
             f"{NET_PORT} TCP portunu yönlendirsin)."]
    for i, ln in enumerate(lines):
        draw_text(ln, small, (225, 230, 225), (W // 2, int(H * 0.26) + i * 30), shadow=False)
    for lab, act, r in mp_menu_buttons():
        draw_button(r, lab, r.collidepoint(mouse_pos), color=(56, 108, 70) if act != "menu" else (110, 60, 60))
    if net_notice:
        draw_text(net_notice, tiny, (255, 110, 100), (W // 2, int(H * 0.46)))


def draw_join():
    draw_backdrop()
    draw_text("ODAYA KATIL", big, (255, 235, 150), (W // 2, int(H * 0.14)))
    draw_text("Host'un sana verdiği IP adresini yaz (örn: 192.168.1.20)", mid, (230, 235, 230),
              (W // 2, int(H * 0.28)), shadow=False)
    box = pygame.Rect(W // 2 - 300, int(H * 0.36), 600, 70)
    pygame.draw.rect(screen, (20, 28, 22), box, border_radius=14)
    pygame.draw.rect(screen, (190, 240, 200), box, 3, border_radius=14)
    caret = "|" if (pygame.time.get_ticks() // 500) % 2 == 0 else " "
    draw_text(join_text + caret, mid, (255, 255, 255), box.center, shadow=False)
    status = connect_info["status"]
    if status == "connecting":
        draw_text("Bağlanılıyor...", tiny, (255, 235, 150), (W // 2, int(H * 0.50)))
    elif net_notice:
        draw_text(net_notice, tiny, (255, 110, 100), (W // 2, int(H * 0.50)))
    draw_text("Yazdıktan sonra Enter'a bas ya da Bağlan'a tıkla", small, (200, 210, 200),
              (W // 2, int(H * 0.54)), shadow=False)
    for lab, act, r in join_buttons():
        draw_button(r, lab, r.collidepoint(mouse_pos), color=(56, 108, 70) if act != "mp" else (110, 60, 60))


def draw_lobby():
    draw_backdrop()
    draw_text("OYUN ODASI", big, (255, 235, 150), (W // 2, int(H * 0.12)))
    if net_mode == "host":
        ip_text = "   /   ".join(host_ips)
        draw_text("Arkadaşlarının yazacağı IP adresi:", mid, (230, 235, 230), (W // 2, int(H * 0.24)),
                  shadow=False)
        draw_text(f"{ip_text}   (port {NET_PORT})", mid, (255, 215, 80), (W // 2, int(H * 0.30)))
        draw_text("İnternetten oynuyorsanız Radmin VPN / ZeroTier / Tailscale IP'sini paylaş.",
                  small, (200, 210, 200), (W // 2, int(H * 0.35)), shadow=False)
        roster = lobby_roster()
    else:
        draw_text("Host oyunu başlatınca oyun otomatik başlayacak...", mid, (230, 235, 230),
                  (W // 2, int(H * 0.26)), shadow=False)
        roster = lobby_players
    draw_text(f"Oyuncular ({len(roster)}/{MAX_PLAYERS})", mid, (255, 255, 255), (W // 2, int(H * 0.42)))
    for i, row in enumerate(roster):
        try:
            pid, name, tid = row[0], row[1], row[2]
        except (TypeError, ValueError, IndexError):
            continue
        col = PLAYER_COLORS[pid % len(PLAYER_COLORS)]
        tname = TANK_BY_ID.get(tid, TANK_BY_ID["acemi"])["name"]
        y = int(H * 0.48) + i * 42
        pygame.draw.rect(screen, col, (W // 2 - 230, y - 14, 28, 28), border_radius=6)
        who = " (sen)" if pid == my_pid else ""
        draw_text(f"{name}{who}  -  {tname}", font, (255, 255, 255), (W // 2 + 20, y), shadow=False)
    for lab, act, r in lobby_buttons():
        draw_button(r, lab, r.collidepoint(mouse_pos), color=(56, 108, 70) if act != "leave" else (110, 60, 60))


def handle_click(pos):
    global new_pc_notice, shop_page
    if state == "menu":
        new_pc_notice = False
    if state == "upgrade":
        for i, r in enumerate(option_rects()):
            if r.collidepoint(pos):
                choose(i)
                return
    elif state == "shop":
        rects, back, prev_b, next_b, tanks = shop_layout()
        if back.collidepoint(pos):
            go_menu_from_shop()
            return
        pages = shop_page_count()
        if pages > 1 and prev_b.collidepoint(pos):
            shop_page = (shop_page - 1) % pages
            return
        if pages > 1 and next_b.collidepoint(pos):
            shop_page = (shop_page + 1) % pages
            return
        for r, tk in zip(rects, tanks):
            if r.collidepoint(pos):
                owned = tk["id"] in data["owned"]
                _main, up_btn = shop_card_buttons(r, owned)
                if up_btn is not None and up_btn.collidepoint(pos):
                    shop_action(tk, "up")
                else:
                    shop_action(tk, "main")
                return
    else:
        for lab, act, r in current_buttons():
            if r.collidepoint(pos):
                do_action(act)
                return


def go_menu_from_shop():
    global state
    state = "menu"
    save_game()


JOIN_CHARS = set("0123456789.:abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-")


def handle_key(key, uni=""):
    global state, need_release, paused_ui, join_text, code_text
    if state == "code":
        if key == pygame.K_ESCAPE:
            state = "menu"
        elif key == pygame.K_RETURN:
            apply_code()
        elif key == pygame.K_BACKSPACE:
            code_text = code_text[:-1]
        elif uni and uni.isalnum() and len(code_text) < 20:
            code_text += uni.upper()
        return
    if state == "mp_join":
        if key == pygame.K_ESCAPE:
            state = "mp_menu"
        elif key == pygame.K_RETURN:
            start_join()
        elif key == pygame.K_BACKSPACE:
            join_text = join_text[:-1]
        elif uni and uni in JOIN_CHARS and len(join_text) < 40:
            join_text += uni
        return
    if key == pygame.K_ESCAPE:
        if state == "menu":
            quit_game()
        elif state == "shop":
            go_menu_from_shop()
        elif state == "mp_menu":
            state = "menu"
        elif state == "lobby":
            leave_net()
            state = "mp_menu"
        elif state == "play":
            paused_ui = not paused_ui
            if not paused_ui:
                need_release = True
        elif state == "over":
            go_menu()
    elif state == "upgrade" and key in (pygame.K_1, pygame.K_2, pygame.K_3):
        choose(key - pygame.K_1)


# ---------------- ana dongu ----------------
reset_game()
state = "menu"
mouse_pos = (0, 0)
mouse_down = False

while running:
    dt = min(clock.tick(60) / 1000, 0.05)
    mouse_pos = to_logical(pygame.mouse.get_pos())
    mouse_down = False if ANDROID else pygame.mouse.get_pressed()[0]
    if not mouse_down:
        need_release = False

    for e in pygame.event.get():
        if e.type == pygame.QUIT:
            quit_game()
        elif ANDROID and e.type == pygame.FINGERDOWN:
            if state == "play" and not paused_ui:
                pos = to_logical((int(e.x * SW), int(e.y * SH)))
                if pos[0] < W * 0.46 and pos[1] > H * 0.42 and touch_move_id is None:
                    touch_move_id = e.finger_id
                    touch_move_pos = pos
                elif pos[0] > W * 0.54 and pos[1] > H * 0.42 and touch_aim_id is None:
                    touch_aim_id = e.finger_id
                    touch_aim_pos = pos
                    ax = pos[0] - TOUCH_AIM_CENTER[0]
                    ay = pos[1] - TOUCH_AIM_CENTER[1]
                    if math.hypot(ax, ay) > 12:
                        touch_aim_angle = math.atan2(ay, ax)
        elif ANDROID and e.type == pygame.FINGERMOTION:
            pos = to_logical((int(e.x * SW), int(e.y * SH)))
            if e.finger_id == touch_move_id:
                touch_move_pos = pos
            elif e.finger_id == touch_aim_id:
                touch_aim_pos = pos
        elif ANDROID and e.type == pygame.FINGERUP:
            if e.finger_id == touch_move_id:
                touch_move_id = None
                touch_move_pos = TOUCH_MOVE_CENTER
            if e.finger_id == touch_aim_id:
                touch_aim_id = None
                touch_aim_pos = TOUCH_AIM_CENTER
        elif e.type == pygame.KEYDOWN:
            handle_key(e.key, getattr(e, "unicode", ""))
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            # Oyun sirasinda Android dokunuslari joystick ile islenir;
            # menulerde SDL'nin dokunma -> fare tiklamasi eslemesi kullanilir.
            if not (ANDROID and state == "play" and not paused_ui):
                handle_click(to_logical(e.pos))

    want_cursor = not (state == "play" and not paused_ui)
    if want_cursor != cursor_visible:
        pygame.mouse.set_visible(want_cursor)
        cursor_visible = want_cursor

    keys = pygame.key.get_pressed()
    update_particles(dt)
    shake = max(0.0, shake - 2.5 * dt)
    hurt = max(0.0, hurt - 2.0 * dt)
    shop_msg_t = max(0.0, shop_msg_t - dt)

    # ---------------- ag ----------------
    if net_mode == "host":
        host_service(dt)
    elif net_mode == "client":
        client_service()
    if state == "mp_join":
        check_connect()

    # ---------------- guncelle (tek kisilik / host) ----------------
    sim_active = state == "play" and net_mode != "client" and not (net_mode == "single" and paused_ui)
    if sim_active:
        elapsed += dt
        for p in players:
            if p.pid == my_pid:
                p.inp = local_input(keys)
            elif host is not None and p.pid in host.inputs:
                set_remote_input(p, host.inputs[p.pid])
        for p in players:
            if p.hp > 0:
                p.update(dt, p.inp, bullets)
        for p in players:                                     # Sok Dalgasi
            if p.hp > 0 and p.shock > 0:
                p.shock_t -= dt
                if p.shock_t <= 0:
                    p.shock_t = max(1.5, 5.0 - 0.8 * p.shock)
                    rad = 200 + 40 * p.shock
                    for en in enemies:
                        if math.hypot(en.x - p.x, en.y - p.y) < rad + en.r:
                            en.hp -= p.dmg * 1.5
                            en.flash = 0.1
                            en.last_pid = p.pid
                    fx_sparks(p.x, p.y, (120, 200, 255), 30, 420, 0.4)
        banner = max(0, banner - dt)
        boss_lvl = is_boss_level(level)
        power = get_power()
        n_pl = len(players)

        if boss_lvl and not boss_spawned:
            enemies.append(Enemy(power, boss=True, hp_mult=1 + 0.8 * (n_pl - 1)))
            boss_spawned = True

        # Dusmanlar surekli yeniden dogar, zamanla guclenir (oyuncu sayisiyla da artar)
        spawn_timer -= dt
        max_alive = int((2 if boss_lvl else min(3 + level // 3, 12)) * (1 + 0.6 * (n_pl - 1)))
        minions = [en for en in enemies if not en.boss]
        if spawn_timer <= 0 and len(minions) < max_alive:
            enemies.append(Enemy(power, hp_mult=1 + 0.3 * (n_pl - 1)))
            spawn_timer = 3.0 if boss_lvl else max(0.6, 1.5 - power * 0.01)

        for en in enemies:
            en.update(dt, players, bullets)
            if en.burn_t > 0:                                 # Yanici Mermi: surekli hasar
                en.burn_t -= dt
                en.hp -= en.burn_dps * dt
                if random.random() < 0.2:
                    spawn_sparks(en.x, en.y, (255, 140, 50), 1, 60, 0.3)

        # tanklar ust uste binmesin (birbirlerine zarar vermezler)
        for i, a in enumerate(enemies):
            for b in enemies[i + 1:]:
                ddx, ddy = b.x - a.x, b.y - a.y
                d = math.hypot(ddx, ddy)
                mind = (a.r + b.r) * 0.95
                if 0 < d < mind:
                    push = (mind - d) / 2
                    a.x -= ddx / d * push
                    a.y -= ddy / d * push
                    b.x += ddx / d * push
                    b.y += ddy / d * push

        pmap = {p.pid: p for p in players}
        for b in bullets:
            b.update(dt)
            if b.life <= 0:
                continue
            if b.owner == "player":
                for en in enemies:
                    if en.eid in b.hit_ids:
                        continue
                    if math.hypot(b.x - en.x, b.y - en.y) < en.r + b.r:
                        en.hp -= b.dmg
                        en.flash = 0.1
                        en.last_pid = b.pid
                        fx_sparks(b.x, b.y, (255, 235, 150), 5, 170, 0.25)
                        if b.lifesteal > 0:                       # Can Calma
                            shooter = pmap.get(b.pid)
                            if shooter is not None and shooter.hp > 0:
                                shooter.hp = min(shooter.max_hp, shooter.hp + b.dmg * b.lifesteal)
                        if b.splash > 0:                          # Patlayici Mermi
                            for other in enemies:
                                if other is not en and math.hypot(other.x - b.x, other.y - b.y) < 110 + other.r:
                                    other.hp -= b.dmg * b.splash
                                    other.flash = 0.1
                                    other.last_pid = b.pid
                            fx_sparks(b.x, b.y, (255, 150, 60), 14, 260, 0.35)
                        if b.slow > 0:                            # Yavaslatici Mermi
                            en.slow_t = 1.0 + 0.5 * b.slow
                        if b.burn > 0:                            # Yanici Mermi
                            en.burn_t = 3.0
                            en.burn_dps = max(en.burn_dps, b.dmg * 0.25 * b.burn)
                        if b.pierce > 0:                          # Delici Mermi
                            b.pierce -= 1
                            b.hit_ids.add(en.eid)
                        else:
                            b.life = 0
                        break
            else:
                for p in players:
                    if p.hp > 0 and math.hypot(b.x - p.x, b.y - p.y) < p.r + b.r:
                        p.hit(b.dmg)
                        fx_sparks(b.x, b.y, (255, 120, 90), 5, 170, 0.25)
                        b.life = 0
                        break
        bullets[:] = [b for b in bullets if b.life > 0]

        for en in enemies:
            if en.hp <= 0:
                fx_explosion(en.x, en.y, 2.2 if en.boss else 1.0, 46 * en.scale)
                fx_shake(0.9 if en.boss else 0.3)
                reward = int(150 + level * 15) if en.boss else int(5 + level * 2)
                killer = pmap.get(en.last_pid)
                if killer is not None and killer.gold > 0:       # Altin Avcisi
                    reward = int(reward * (1 + killer.gold))
                if en.last_pid == my_pid:
                    data["money"] += reward
                    run_money += reward
                    popups.append([en.x, en.y - en.r, f"+{reward} $", 1.3])
                elif en.last_pid >= 0:
                    fx_events.append(["$", en.last_pid, reward, int(en.x), int(en.y - en.r)])
                if not en.boss:
                    kills += 1
                score += int((200 if en.boss else 10) * level)
        enemies[:] = [en for en in enemies if en.hp > 0]

        for p in players:
            if p.hp <= 0 and not p.dead_fx:
                p.dead_fx = True
                fx_explosion(p.x, p.y, 1.8, 70)
                fx_shake(1.0)

        if all(p.hp <= 0 for p in players):          # herkes yenildi
            state = "over"
            if net_mode == "single":
                data["run"] = None
            data["best_score"] = max(data["best_score"], int(score))
            data["best_level"] = max(data["best_level"], level)
            save_game()
        else:
            if boss_lvl:
                done = boss_spawned and not any(en.boss for en in enemies)
            else:
                done = kills >= kills_needed
            if done:
                enemies.clear()
                bullets.clear()
                for p in players:
                    if p.hp <= 0:              # yenilenler bir sonraki levelde yari canla geri doner
                        p.hp = p.max_hp * 0.5
                        p.dead_fx = False
                    else:
                        p.hp = min(p.max_hp, p.hp + 25)
                level += 1
                data["best_level"] = max(data["best_level"], level)
                if (level - 1) % UPGRADE_EVERY == 0:
                    for p in players:
                        p.opts = roll_options(p)
                        p.picked = False
                    options = [UPGRADES[i] for i in player.opts]
                    upgrade_t = 30.0
                    state = "upgrade"
                    if net_mode == "host":
                        host_send_options()
                else:
                    start_level()
                save_progress()

    # ---------------- yukseltme secimi (herkes secince devam) ----------------
    if state == "upgrade" and net_mode != "client":
        if net_mode == "host":
            upgrade_t -= dt
            if upgrade_t <= 0:
                for p in players:
                    if not p.picked and p.opts:
                        apply_pick(p, random.randrange(len(p.opts)))
        if all(p.picked for p in players):
            state = "play"
            start_level()
            need_release = True

    # ---------------- istemci guncelleme ----------------
    if net_mode == "client" and state in ("play", "upgrade", "over"):
        client_update(dt)
        if state == "play":
            input_acc += dt
            if input_acc >= 1.0 / INPUT_HZ:
                input_acc = 0.0
                client_send_input(local_input(keys))

    # ---------------- host: durum paketi gonder ----------------
    if net_mode == "host" and state in ("play", "upgrade", "over"):
        net_acc += dt
        if net_acc >= 1.0 / SNAP_HZ:
            net_acc = 0.0
            host_send_snapshot()
    elif net_mode != "host":
        fx_events.clear()

    # ---------------- ciz ----------------
    if state == "menu":
        draw_menu()
    elif state == "shop":
        draw_shop()
    elif state == "mp_menu":
        draw_mp_menu()
    elif state == "code":
        draw_code()
    elif state == "mp_join":
        draw_join()
    elif state == "lobby":
        draw_lobby()
    else:
        canvas.blit(background, (0, 0))
        for en in sorted(enemies, key=lambda e: e.y):
            en.draw(canvas)
        for p in players:
            if p.hp > 0:
                p.draw(canvas)
        for b in bullets:
            b.draw(canvas)
        draw_particles(canvas)

        ox = random.uniform(-1, 1) * shake * 14
        oy = random.uniform(-1, 1) * shake * 14
        screen.fill((0, 0, 0))
        screen.blit(canvas, (int(ox), int(oy)))
        screen.blit(vignette, (0, 0))
        if hurt > 0:
            hurt_surf.fill((255, 0, 0, int(90 * hurt)))
            screen.blit(hurt_surf, (0, 0))
        for q in popups:
            draw_text(q[2], tiny, (255, 220, 90), (int(q[0]), int(q[1])))

        # ---------------- HUD ----------------
        panel((14, 14, 340, 92))
        ratio = max(0, player.hp) / player.max_hp
        bar_col = lerp_color((230, 60, 50), (70, 210, 90), ratio)
        pygame.draw.rect(screen, (35, 15, 15), (26, 26, 316, 24), border_radius=8)
        if ratio > 0:
            pygame.draw.rect(screen, bar_col, (26, 26, 316 * ratio, 24), border_radius=8)
        pygame.draw.rect(screen, (255, 255, 255), (26, 26, 316, 24), 2, border_radius=8)
        draw_text(f"{int(max(0, player.hp))} / {int(player.max_hp)}", tiny, (255, 255, 255), (184, 38))
        screen.blit(font.render(f"Level {level}     Skor {score}", True, (255, 255, 255)), (26, 58))
        if player.shield:
            screen.blit(tiny.render(f"Kalkan x{player.shield}", True, (130, 200, 255)), (250, 62))

        # takim arkadaslari
        others = [p for p in players if p is not player]
        if others and state != "over":
            panel((14, 114, 340, 14 + 30 * len(others)))
            for i, p in enumerate(others):
                yy = 128 + i * 30
                col = PLAYER_COLORS[p.pid % len(PLAYER_COLORS)]
                screen.blit(micro.render(p.name, True, col), (26, yy - 8))
                pygame.draw.rect(screen, (35, 15, 15), (140, yy - 6, 190, 14), border_radius=6)
                if p.hp > 0:
                    pygame.draw.rect(screen, col, (140, yy - 6, 190 * min(1, p.hp / p.max_hp), 14),
                                     border_radius=6)
                else:
                    screen.blit(micro.render("YENİLDİ", True, (255, 120, 110)), (190, yy - 8))

        panel((W - 330, 14, 316, 118))
        if is_boss_level(level):
            info, info_col = "BOSS SAVAŞI!", (255, 170, 70)
        else:
            info, info_col = f"Yok edilen: {min(kills, kills_needed)} / {kills_needed}", (235, 235, 150)
        screen.blit(font.render(info, True, info_col), (W - 316, 24))
        screen.blit(small.render(f"Süre {fmt_time(elapsed)}   Düşman gücü {get_power():.1f}", True,
                                 (225, 225, 225)), (W - 316, 58))
        screen.blit(font.render(f"Para: {data['money']} $", True, (255, 215, 80)), (W - 316, 86))

        stats = (f"{player.tank['name']}   Namlu x{player.shots}   Hasar {int(player.dmg)}   "
                 f"Atış {1 / player.cooldown:.1f}/sn   Hız {int(player.speed)}   "
                 f"Sekme {player.bounces}   Yenilenme {player.regen:.1f}")
        st_img = tiny.render(stats, True, (235, 235, 235))
        panel((14, H - 46, st_img.get_width() + 28, 34))
        screen.blit(st_img, (28, H - 39))
        if god_active():
            draw_text("GODMODE AÇIK", tiny, (255, 215, 80), (W // 2, H - 30))

        for en in enemies:
            if en.boss:
                bw = W * 0.45
                bx = (W - bw) / 2
                panel((bx - 12, 12, bw + 24, 46))
                pygame.draw.rect(screen, (40, 10, 50), (bx, 24, bw, 24), border_radius=8)
                br_ = max(0, en.hp) / en.max_hp
                if br_ > 0:
                    pygame.draw.rect(screen, (195, 85, 225), (bx, 24, bw * br_, 24), border_radius=8)
                pygame.draw.rect(screen, (255, 255, 255), (bx, 24, bw, 24), 2, border_radius=8)
                draw_text("BOSS", tiny, (255, 255, 255), (W // 2, 36))

        if state == "play" and player.hp <= 0 and not paused_ui:
            draw_text("Yenildin! Takım arkadaşların savaşıyor, level bitince geri döneceksin.", mid,
                      (255, 150, 140), (W // 2, int(H * 0.88)))

        if state == "play" and banner > 0:
            if is_boss_level(level):
                draw_text(f"LEVEL {level} - BOSS!", big, (255, 170, 70), (W // 2, H // 3))
            else:
                draw_text(f"LEVEL {level}", big, (255, 255, 255), (W // 2, H // 3))

        if state == "upgrade":
            screen.blit(veil_dark, (0, 0))
            draw_text(f"LEVEL {level - 1} TAMAMLANDI!", big, (255, 255, 255), (W // 2, H // 2 - 220))
            if player.picked:
                waiting = [p for p in players if not p.picked]
                msg = "Seçtin! Diğer oyuncular bekleniyor..." if net_mode != "single" else "Seçtin!"
                draw_text(msg, mid, (235, 235, 150), (W // 2, H // 2 - 150))
            else:
                draw_text("3 yeni özellikten birini seç (tıkla veya 1 / 2 / 3)", mid, (235, 235, 150),
                          (W // 2, H // 2 - 150))
            if net_mode != "single":
                draw_text(f"Otomatik seçime kalan süre: {max(0, int(upgrade_t))} sn", small,
                          (210, 215, 210), (W // 2, H // 2 - 110), shadow=False)
            for i, (r, opt) in enumerate(zip(option_rects(), options)):
                hover = r.collidepoint(mouse_pos) and not player.picked
                pygame.draw.rect(screen, (46, 72, 52) if hover else (28, 42, 32), r, border_radius=18)
                pygame.draw.rect(screen, shade(opt[4], 1.2 if hover else 0.9), r, 4 if hover else 3,
                                 border_radius=18)
                ball(screen, r.centerx, r.y + 62, 30, opt[4])
                draw_text(f"[{i + 1}]", tiny, (255, 255, 130), (r.x + 28, r.y + 22))
                draw_text(opt[0], mid, (255, 255, 255), (r.centerx, r.y + 135))
                for li, ln in enumerate(wrap_text(opt[1], small, r.width - 40)):
                    draw_text(ln, small, (215, 232, 215), (r.centerx, r.y + 185 + li * 24), shadow=False)

        if state == "play" and paused_ui:
            screen.blit(veil_dark, (0, 0))
            draw_text("DURAKLATILDI" if net_mode == "single" else "MENÜ (oyun devam ediyor)", big,
                      (255, 255, 255), (W // 2, H // 2 - 150))
            for lab, act, r in pause_buttons():
                draw_button(r, lab, r.collidepoint(mouse_pos),
                            color=(56, 108, 70) if act == "resume" else (110, 60, 60))

        if state == "over":
            screen.blit(veil_dark, (0, 0))
            draw_text("OYUN BİTTİ", big, (255, 90, 90), (W // 2, H // 2 - 130))
            draw_text(f"Level {level}   |   Skor {score}   |   Süre {fmt_time(elapsed)}", mid,
                      (255, 255, 255), (W // 2, H // 2 - 60))
            draw_text(f"Bu oyunda kazanılan: +{run_money} $     Toplam para: {data['money']} $", mid,
                      (255, 215, 80), (W // 2, H // 2 - 10))
            if net_mode == "client":
                draw_text("Host yeniden başlatırsa otomatik katılırsın.", small, (210, 215, 210),
                          (W // 2, H // 2 + 40), shadow=False)
            for lab, act, r in over_buttons():
                draw_button(r, lab, r.collidepoint(mouse_pos))

        if state == "play" and not paused_ui and not ANDROID:
            mx, my = mouse_pos
            pygame.draw.circle(screen, (0, 0, 0), (int(mx), int(my)), 16, 4)
            pygame.draw.circle(screen, (255, 255, 255), (int(mx), int(my)), 15, 2)
            for ddx, ddy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                pygame.draw.line(screen, (255, 255, 255), (mx + ddx * 9, my + ddy * 9),
                                 (mx + ddx * 22, my + ddy * 22), 2)
            pygame.draw.circle(screen, (255, 70, 70), (int(mx), int(my)), 3)

    if ANDROID and state == "play" and not paused_ui:
        draw_touch_controls()
    present()

pygame.quit()
sys.exit()
