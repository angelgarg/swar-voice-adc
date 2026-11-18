"""Swar concept board, built procedurally.  Units: 1 = 1 cm.

  blender -b -P swar_scene.py -- --view hero --out renders/swar_hero.png
  blender -b -P swar_scene.py -- --view chip --out renders/swar_chip.png
  options: --samples N  --scale PCT  --save file.blend
"""
import argparse
import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--view", default="hero", choices=["hero", "chip", "anim"])
ap.add_argument("--frames", type=int, nargs=2, default=[1, 216])
ap.add_argument("--out", default=os.path.join(HERE, "renders", "swar.png"))
ap.add_argument("--samples", type=int, default=160)
ap.add_argument("--scale", type=int, default=100)
ap.add_argument("--save", default="")
args = ap.parse_args(argv)

LAYOUT_PNG = os.path.join(HERE, "..", "docs", "chip_pinout_blocks_4x4.png")
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# ---------------------------------------------------------------- scene reset
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
col = scene.collection
font = bpy.data.fonts.load(FONT_PATH) if os.path.exists(FONT_PATH) else None


# ------------------------------------------------------------------ materials
def mat(name, color, metallic=0.0, rough=0.5, emit=None, estr=0.0, coat=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = rough
    b.inputs["Coat Weight"].default_value = coat
    b.inputs["Coat Roughness"].default_value = 0.08
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1)
        b.inputs["Emission Strength"].default_value = estr
    return m


M_MASK = mat("soldermask", (0.006, 0.012, 0.022), rough=0.32, coat=0.6)
M_FR4 = mat("fr4", (0.10, 0.085, 0.04), rough=0.7)
M_GOLD = mat("gold", (1.0, 0.72, 0.30), metallic=1, rough=0.22)
M_GOLD_T = mat("gold_trace", (0.95, 0.66, 0.26), metallic=1, rough=0.34)
M_SILVER = mat("silver", (0.86, 0.87, 0.88), metallic=1, rough=0.28)
M_STEEL = mat("steel", (0.62, 0.63, 0.65), metallic=1, rough=0.38)
M_CERAMIC = mat("ceramic", (0.03, 0.008, 0.06), rough=0.42, coat=0.3)
M_EPOXY = mat("epoxy", (0.012, 0.012, 0.014), rough=0.42)
M_FELT = mat("felt", (0.008, 0.008, 0.008), rough=0.95)
M_SILK = mat("silk", (0.85, 0.87, 0.9), rough=0.6)
M_SILK_DIM = mat("silk_dim", (0.33, 0.37, 0.43), rough=0.6)
M_ETCH = mat("etch", (0.30, 0.31, 0.33), rough=0.5)
M_ETCH_DARK = mat("etch_dark", (0.015, 0.015, 0.02), rough=0.6)
M_LEGEND = mat("legend", (1.0, 0.86, 0.55), rough=0.5, emit=(1.0, 0.78, 0.4), estr=1.6)
M_ACCENT = mat("accent", (1.0, 0.55, 0.12), rough=0.5, emit=(1.0, 0.45, 0.08), estr=1.2)
M_LED_OFF = mat("led_off", (0.55, 0.6, 0.58), rough=0.25, coat=0.5)
M_LED_ON = mat("led_on", (0.2, 1.0, 0.45), rough=0.3, emit=(0.1, 1.0, 0.35), estr=45)
M_FLOOR = mat("floor", (0.012, 0.014, 0.02), rough=0.22)
M_SILICON = mat("silicon", (0.05, 0.055, 0.07), metallic=0.9, rough=0.25)


def die_material():
    """Layout image, lightness-inverted so the die reads dark with coloured metal."""
    m = bpy.data.materials.new("die")
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(LAYOUT_PNG)
    tex.extension = "EXTEND"
    inv = nt.nodes.new("ShaderNodeInvert")
    hue = nt.nodes.new("ShaderNodeHueSaturation")
    hue.inputs["Hue"].default_value = 0.0          # 0.0 == 180 deg shift
    hue.inputs["Saturation"].default_value = 1.25
    hue.inputs["Value"].default_value = 0.8
    nt.links.new(tex.outputs["Color"], inv.inputs["Color"])
    nt.links.new(inv.outputs["Color"], hue.inputs["Color"])
    nt.links.new(hue.outputs["Color"], b.inputs["Base Color"])
    nt.links.new(hue.outputs["Color"], b.inputs["Emission Color"])
    b.inputs["Emission Strength"].default_value = 0.22
    b.inputs["Roughness"].default_value = 0.18
    b.inputs["Metallic"].default_value = 0.35
    b.inputs["Coat Weight"].default_value = 1.0
    b.inputs["Coat Roughness"].default_value = 0.03
    return m


# ------------------------------------------------------------------- geometry
def _obj(name, bm, material):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    if material:
        me.materials.append(material)
    return ob


def box(name, size, loc, material, bevel=0.0):
    """Axis-aligned box, `loc` is its centre."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    ob = _obj(name, bm, material)
    ob.location = loc
    if bevel > 0:
        md = ob.modifiers.new("bevel", "BEVEL")
        md.width = bevel
        md.segments = 3
        md.limit_method = "ANGLE"
    return ob


def cyl(name, r, h, loc, material, segs=72, r_top=None):
    """Cylinder standing on z = loc.z (loc is the centre of its base)."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=segs, radius1=r,
                          radius2=r if r_top is None else r_top, depth=h)
    for f in bm.faces:
        f.smooth = abs(f.normal.z) < 0.5
    for e in bm.edges:
        if len(e.link_faces) == 2 and e.link_faces[0].smooth != e.link_faces[1].smooth:
            e.smooth = False
    ob = _obj(name, bm, material)
    ob.location = (loc[0], loc[1], loc[2] + h / 2)
    return ob


def text(body, loc, size, material, align="CENTER", rot_z=0.0, extrude=0.0015, spacing=1.0):
    cu = bpy.data.curves.new("txt_" + body[:12], "FONT")
    cu.body = body
    cu.size = size
    cu.extrude = extrude
    cu.align_x = align
    cu.align_y = "CENTER"
    cu.space_character = spacing
    if font:
        cu.font = font
    cu.materials.append(material)
    ob = bpy.data.objects.new("txt_" + body[:12], cu)
    ob.location = loc
    ob.rotation_euler = (0, 0, rot_z)
    col.objects.link(ob)
    return ob


def trace(points, width=0.035, z=0.003, material=None):
    """Copper trace through axis-aligned 2D points."""
    material = material or M_GOLD_T
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        sx = abs(x1 - x0) + width
        sy = abs(y1 - y0) + width
        box("trace", (sx, sy, z), ((x0 + x1) / 2, (y0 + y1) / 2, z / 2), material)


def wire(p0, p1, rise, material, radius=0.0022, n=18):
    """Bond wire: an arc from p0 to p1 that loops `rise` above the straight line."""
    cu = bpy.data.curves.new("wire", "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = radius
    cu.bevel_resolution = 3
    sp = cu.splines.new("POLY")
    sp.points.add(n - 1)
    a, b = Vector(p0), Vector(p1)
    for i in range(n):
        t = i / (n - 1)
        p = a.lerp(b, t)
        # skewed loop: rises fast off the die, lands shallow on the finger
        p.z += rise * math.sin(math.pi * t ** 0.7)
        sp.points[i].co = (p.x, p.y, p.z, 1)
    cu.materials.append(material)
    ob = bpy.data.objects.new("wire", cu)
    col.objects.link(ob)
    return ob


# ---------------------------------------------------------------------- board
BW, BH, BT = 12.4, 8.6, 0.16
board = box("board", (BW, BH, BT), (0, 0, -BT / 2), M_MASK, bevel=0.03)
box("board_core", (BW + 0.004, BH + 0.004, BT * 0.55), (0, 0, -BT / 2), M_FR4)
for sx in (-1, 1):
    for sy in (-1, 1):
        x, y = sx * (BW / 2 - 0.45), sy * (BH / 2 - 0.45)
        cyl("mnt_ring", 0.26, 0.004, (x, y, 0), M_GOLD)
        cyl("mnt_hole", 0.14, 0.006, (x, y, 0), M_FELT)

# ---------------------------------------------------------- DIP-40 ADC package
DX, DY = 1.2, 2.25            # package centre
BODY = (5.2, 1.42, 0.30)
BZ0 = 0.09                    # underside height above board
BTOP = BZ0 + BODY[2]
CAV, CAV_D = 0.92, 0.13       # cavity opening and depth
body = box("dip_body", BODY, (DX, DY, BZ0 + BODY[2] / 2), M_CERAMIC)
cut = box("dip_cut", (CAV, CAV, CAV_D * 2), (DX, DY, BTOP), None)
cut.hide_render = True
cut.display_type = "WIRE"
bo = body.modifiers.new("cavity", "BOOLEAN")
bo.operation = "DIFFERENCE"
bo.object = cut
bv = body.modifiers.new("bevel", "BEVEL")
bv.width, bv.segments, bv.limit_method = 0.012, 2, "ANGLE"

# gold seal ring round the cavity
RW, RO = 0.10, CAV / 2 + 0.03
for sx, sy, size in ((0, 1, (2 * RO + 2 * RW, RW, 0.012)), (0, -1, (2 * RO + 2 * RW, RW, 0.012)),
                     (1, 0, (RW, 2 * RO, 0.012)), (-1, 0, (RW, 2 * RO, 0.012))):
    box("seal", size, (DX + sx * (RO + RW / 2), DY + sy * (RO + RW / 2), BTOP + 0.006), M_GOLD)

# pin-1 notch mark and package legend
cyl("pin1", 0.07, 0.004, (DX - BODY[0] / 2 + 0.22, DY - 0.42, BTOP), M_GOLD)
text("SWAR-ADC8", (DX - 1.55, DY + 0.16, BTOP), 0.25, M_LEGEND, spacing=1.05)
text("8-bit SAR  Rev3.2", (DX - 1.55, DY - 0.2, BTOP), 0.13, M_LEGEND)
text("SCL 1.2 µm CMOS", (DX + 1.6, DY + 0.16, BTOP), 0.17, M_LEGEND)
text("DESIGNED IN INDIA", (DX + 1.6, DY - 0.2, BTOP), 0.115, M_LEGEND, spacing=1.1)

# pins (side-brazed, gold) + pads
PIN_X = [DX - 2.413 + 0.254 * i for i in range(20)]
for px in PIN_X:
    for s in (-1, 1):
        py = DY + s * (BODY[1] / 2 + 0.012)
        box("pin_sh", (0.13, 0.024, 0.20), (px, py, BZ0 + 0.16), M_GOLD)
        box("pin", (0.05, 0.024, 0.20), (px, py, 0.02), M_GOLD)
        cyl("pad", 0.085, 0.004, (px, py, 0), M_GOLD, segs=24)

# cavity contents: die-attach pad, die, layout, fingers, bond wires
CZ = BTOP - CAV_D
DIE, DIE_T = 0.40, 0.03
box("attach", (0.52, 0.52, 0.006), (DX, DY, CZ + 0.003), M_GOLD)
box("die", (DIE, DIE, DIE_T), (DX, DY, CZ + 0.006 + DIE_T / 2), M_SILICON)
bm = bmesh.new()
h = DIE / 2 - 0.004
vs = [bm.verts.new((sx * h, sy * h, 0)) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
f = bm.faces.new(vs)
uv = bm.loops.layers.uv.new()
U0, U1 = 0.034, 0.966          # crop the white margin of the layout image
for loop, (u, v) in zip(f.loops, ((U0, U0), (U1, U0), (U1, U1), (U0, U1))):
    loop[uv].uv = (u, v)
DIE_MAT = die_material()
die_top = _obj("die_layout", bm, DIE_MAT)
DIE_Z = CZ + 0.006 + DIE_T + 0.0006
die_top.location = (DX, DY, DIE_Z)

N_SIDE = 10
for side in range(4):
    for i in range(N_SIDE):
        t = (i + 0.5) / N_SIDE - 0.5
        pad = Vector((t * (DIE - 0.07), DIE / 2 - 0.022, 0))
        fin = Vector((t * (CAV - 0.36), CAV / 2 - 0.075, 0))
        rot = side * math.pi / 2
        c, s = math.cos(rot), math.sin(rot)
        px, py = pad.x * c - pad.y * s, pad.x * s + pad.y * c
        fx, fy = fin.x * c - fin.y * s, fin.x * s + fin.y * c
        size = (0.03, 0.13, 0.005) if side % 2 == 0 else (0.13, 0.03, 0.005)
        box("finger", size, (DX + fx, DY + fy, CZ + 0.0025), M_GOLD)
        wire((DX + px, DY + py, DIE_Z), (DX + fx * 0.93, DY + fy * 0.93, CZ + 0.005), 0.045, M_GOLD)

text("8-BIT SAR ADC  ·  2 MS/s", (DX, DY + 1.55, 0.001), 0.2, M_SILK, spacing=1.05)
text("U1", (DX - 2.95, DY, 0.001), 0.15, M_SILK_DIM)

# ----------------------------------------------------------------- microphone
MX, MY = -4.75, 2.25
cyl("mic_can", 0.49, 0.42, (MX, MY, 0.0), M_SILVER, segs=96)
cyl("mic_rim", 0.49, 0.03, (MX, MY, 0.42), M_STEEL, segs=96, r_top=0.46)
cyl("mic_felt", 0.42, 0.012, (MX, MY, 0.445), M_FELT, segs=96)
cyl("mic_port", 0.07, 0.006, (MX, MY, 0.456), M_ETCH_DARK, segs=32)
text("MIC", (MX, MY + 0.95, 0.001), 0.2, M_SILK, spacing=1.1)
# stylised sound-wave arcs on the silk, left of the capsule
ARC_MATS = []
for k, r in enumerate((0.72, 0.92, 1.12)):
    cu = bpy.data.curves.new("arc", "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = 0.012
    sp = cu.splines.new("POLY")
    n = 24
    sp.points.add(n - 1)
    for i in range(n):
        a = math.radians(150 + 60 * i / (n - 1))
        sp.points[i].co = (MX + r * math.cos(a), MY + r * math.sin(a), 0.004, 1)
    ARC_MATS.append(mat("arc%d" % k, (1.0, 0.55, 0.12), rough=0.5, emit=(1.0, 0.45, 0.08), estr=1.2))
    cu.materials.append(ARC_MATS[-1])
    ob = bpy.data.objects.new("arc", cu)
    col.objects.link(ob)

# ------------------------------------------------------- preamp + S/H (SOIC-8)
PX, PY = -3.05, 2.25
box("pre_body", (0.5, 0.40, 0.15), (PX, PY, 0.095), M_EPOXY, bevel=0.012)
for i in range(4):
    for s in (-1, 1):
        box("pre_pin", (0.042, 0.11, 0.02), (PX - 0.19 + 0.127 * i, PY + s * 0.25, 0.012), M_SILVER)
text("PREAMP + S/H", (PX, PY + 0.62, 0.001), 0.115, M_SILK)
cyl("pre_dot", 0.025, 0.002, (PX - 0.18, PY - 0.12, 0.17), M_ETCH, segs=20)
# a few passives
for (x, y, m) in ((-3.75, 2.62, M_STEEL), (-3.75, 1.88, M_STEEL), (-2.35, 1.72, M_STEEL),
                  (-2.35, 2.78, M_STEEL)):
    box("smd", (0.16, 0.08, 0.06), (x, y, 0.03), mat("smd_body", (0.16, 0.10, 0.05), rough=0.5))
    for s in (-1, 1):
        box("smd_end", (0.035, 0.085, 0.064), (x + s * 0.075, y, 0.032), m)

# ----------------------------------------------------------------------- FPGA
FX, FY, FS = -0.55, -0.95, 2.0
box("fpga", (FS, FS, 0.14), (FX, FY, 0.09), M_EPOXY, bevel=0.02)
NP = 18
for i in range(NP):
    o = (i - (NP - 1) / 2) * 0.1
    for s in (-1, 1):
        box("fp", (0.045, 0.16, 0.018), (FX + o, FY + s * (FS / 2 + 0.06), 0.012), M_SILVER)
        box("fp", (0.16, 0.045, 0.018), (FX + s * (FS / 2 + 0.06), FY + o, 0.012), M_SILVER)
FZ = 0.161
text("FPGA", (FX, FY + 0.33, FZ), 0.42, M_ETCH, spacing=1.08)
text("CIC ÷25  +  FIR ÷5", (FX, FY - 0.18, FZ), 0.15, M_ETCH)
text("2 MS/s  to  16 kHz", (FX, FY - 0.46, FZ), 0.15, M_ETCH)
cyl("fpga_dot", 0.06, 0.002, (FX - 0.78, FY - 0.78, 0.16), M_ETCH, segs=24)
text("DECIMATION FILTER", (FX, FY - 1.42, 0.001), 0.14, M_SILK, spacing=1.05)

# ------------------------------------------------------------ ESP32-S3 module
EX, EY = 3.55, -0.95
EW, EL = 1.8, 2.55
box("esp_pcb", (EL, EW, 0.08), (EX, EY, 0.06), mat("esp_pcb", (0.01, 0.01, 0.012), rough=0.4, coat=0.4))
box("esp_can", (1.72, 1.58, 0.21), (EX - 0.36, EY, 0.205), M_SILVER, bevel=0.03)
text("ESP32-S3", (EX - 0.36, EY + 0.22, 0.311), 0.24, M_ETCH_DARK, spacing=1.03)
text("log-mel + CNN", (EX - 0.36, EY - 0.12, 0.311), 0.14, M_ETCH_DARK)
text("21.7k parameters", (EX - 0.36, EY - 0.38, 0.311), 0.12, M_ETCH_DARK)
# meander antenna on the exposed end
ax = EX + 0.62
ant = [(ax, EY - 0.7)]
for k in range(6):
    x = ax + 0.11 * k
    ant += [(x, EY + 0.7 if k % 2 == 0 else EY - 0.7), (x + 0.11, EY + 0.7 if k % 2 == 0 else EY - 0.7)]
for (x0, y0), (x1, y1) in zip(ant, ant[1:]):
    box("ant", (abs(x1 - x0) + 0.035, abs(y1 - y0) + 0.035, 0.004),
        ((x0 + x1) / 2, (y0 + y1) / 2, 0.102), M_GOLD)
for i in range(14):
    for s in (-1, 1):
        box("esp_pad", (0.07, 0.09, 0.03), (EX - 1.1 + 0.127 * i, EY + s * (EW / 2 + 0.01), 0.02), M_GOLD)
text("KEYWORD AI  ·  ON-DEVICE", (EX, EY - 1.42, 0.001), 0.14, M_SILK, spacing=1.05)

# ------------------------------------------------------------- keyword LEDs
WORDS = ["yes", "no", "up", "down", "left", "right", "on", "off", "stop", "go"]
LIT = "on"
LY = -3.25
LX0, LPITCH = -2.55, 0.78
for i, w in enumerate(WORDS):
    x = LX0 + i * LPITCH
    on = (w == LIT)
    box("led_base", (0.24, 0.15, 0.03), (x, LY, 0.015), M_SILVER)
    box("led", (0.19, 0.13, 0.07), (x, LY, 0.065), M_LED_ON if on else M_LED_OFF, bevel=0.02)
    text(w.upper(), (x, LY - 0.36, 0.001), 0.14, M_LED_ON if on else M_SILK_DIM)
    if on:
        pl = bpy.data.lights.new("led_glow", "POINT")
        pl.energy = 9
        pl.color = (0.15, 1.0, 0.4)
        pl.shadow_soft_size = 0.08
        po = bpy.data.objects.new("led_glow", pl)
        po.location = (x, LY, 0.35)
        col.objects.link(po)
        LED_LIGHT, LED_X = pl, x

# ---------------------------------------------------------------- brand block
text("SWAR", (-4.35, -0.55, 0.001), 1.0, M_SILK, spacing=1.06, extrude=0.003)
box("brand_rule", (2.9, 0.035, 0.004), (-4.35, -1.2, 0.002), M_ACCENT)
text("OFFLINE VOICE AI", (-4.35, -1.5, 0.001), 0.21, M_SILK, spacing=1.12)
text("on a home-grown ADC chip", (-4.35, -1.85, 0.001), 0.15, M_SILK_DIM)
text("no cloud  ·  no imported codec", (-4.35, -3.4, 0.001), 0.13, M_SILK_DIM)

# --------------------------------------------------------------------- traces
pin_y_lo = DY - BODY[1] / 2 - 0.012
trace([(MX + 0.49, MY), (PX - 0.3, MY)], width=0.05)                    # mic -> preamp
trace([(PX + 0.3, MY - 0.25), (PX + 0.3, 1.2), (PIN_X[1], 1.2), (PIN_X[1], pin_y_lo)], width=0.05)  # -> VIN
for k in range(8):                                                       # DOUT[7:0] -> FPGA
    px = PIN_X[5 + k]
    yk = 1.02 - 0.075 * k
    tx = FX - 0.75 + 0.1 * k
    trace([(px, pin_y_lo), (px, yk), (tx, yk), (tx, FY + FS / 2 + 0.06)], width=0.03)
for k in range(3):                                                       # FPGA -> ESP32 (UART)
    y = FY + 0.2 - 0.2 * k
    trace([(FX + FS / 2 + 0.06, y), (EX - EL / 2, y)], width=0.035)
for i in range(len(WORDS)):                                              # ESP32 -> LEDs
    x = LX0 + i * LPITCH
    yb = LY + 0.5 + 0.045 * (i if i < 5 else 9 - i)
    trace([(x, LY + 0.08), (x, yb)], width=0.028)
trace([(LX0, LY + 0.5), (LX0 + 9 * LPITCH, LY + 0.5)], width=0.028)
trace([(EX + 0.4, LY + 0.5), (EX + 0.4, EY - EW / 2)], width=0.028)
text("DOUT[7:0]", (PIN_X[13] + 0.85, 0.8, 0.001), 0.115, M_SILK_DIM)
text("UART", ((FX + FS / 2 + EX - EL / 2) / 2, FY + 0.42, 0.001), 0.115, M_SILK_DIM)

# ------------------------------------------------------------ stage and light
floor = box("floor", (400, 400, 0.1), (0, 0, -BT - 0.25), M_FLOOR)
world = bpy.data.worlds.new("world")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.004, 0.005, 0.008, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.0


def area(name, loc, target, size, energy, color=(1, 1, 1)):
    li = bpy.data.lights.new(name, "AREA")
    li.shape = "RECTANGLE"
    li.size, li.size_y = size
    li.energy = energy
    li.color = color
    ob = bpy.data.objects.new(name, li)
    ob.location = loc
    ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    col.objects.link(ob)
    return ob


area("key", (-9, -9, 15), (0, 0, 0), (16, 10), 9000, (1.0, 0.95, 0.88))
area("rim", (12, 13, 5), (0, 0, 0), (20, 4), 3200, (0.55, 0.72, 1.0))
area("fill", (13, -8, 6), (0, 0, 0), (8, 8), 1500, (0.8, 0.86, 1.0))
area("strip", (0, -1, 13), (0, 1, 0), (26, 1.6), 3500, (1.0, 1.0, 1.0))

# ---------------------------------------------------------------------- camera
cam_d = bpy.data.cameras.new("cam")
cam = bpy.data.objects.new("cam", cam_d)
col.objects.link(cam)
scene.camera = cam
cam_d.clip_start, cam_d.clip_end = 0.05, 500
cam_d.dof.use_dof = True
if args.view in ("hero", "anim"):
    loc, tgt = Vector((-3.4, -17.0, 14.5)), Vector((0.0, -0.25, 0.0))
    cam_d.lens = 54
    cam_d.dof.aperture_fstop = 0.9
    focus = Vector((DX, DY - 1.0, 0.2))
else:
    tgt = Vector((DX + 0.05, DY - 0.02, BTOP - 0.05))
    loc = tgt + Vector((-1.0, -2.55, 2.05))
    for ob in col.objects:
        if ob.type == "LIGHT" and ob.name in ("key", "rim", "fill", "strip"):
            ob.data.energy *= 0.4
    cam_d.lens = 90
    cam_d.dof.aperture_fstop = 0.75
    focus = Vector((DX, DY, DIE_Z))
    # a small light aimed into the cavity so the die and wires sparkle
    area("cavity", (DX + 1.2, DY - 1.0, 3.2), (DX, DY, CZ), (1.2, 1.2), 110, (1.0, 0.97, 0.9))
cam.location = loc
cam.rotation_euler = (tgt - loc).to_track_quat("-Z", "Y").to_euler()
cam_d.dof.focus_distance = (focus - loc).length

# ------------------------------------------------------------------ animation
def keys(idblock, path, pairs):
    for f, v in pairs:
        if path == "default_value":
            idblock.default_value = v
        else:
            setattr(idblock, path, v)
        idblock.keyframe_insert(path, frame=f)


def linear(idb):
    ad = idb.animation_data
    if ad and ad.action:
        for fc in ad.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"


def dot(path, f0, f1, color, r=0.04, z=0.05):
    """A glowing dot that runs along a 2D polyline between frames f0 and f1."""
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=r)
    for f in bm.faces:
        f.smooth = True
    m = mat("dot", color, rough=0.4, emit=color, estr=70)
    ob = _obj("dot", bm, m)
    seg = [(Vector(a) - Vector(b)).length for a, b in zip(path, path[1:])]
    total, acc = sum(seg), 0.0
    for i, p in enumerate(path):
        ob.location = (p[0], p[1], z)
        ob.keyframe_insert("location", frame=f0 + (f1 - f0) * acc / total)
        if i < len(seg):
            acc += seg[i]
    for f, sc in ((f0 - 2, 0.0), (f0, 1.0), (f1, 1.0), (f1 + 2, 0.0)):
        ob.scale = (sc, sc, sc)
        ob.keyframe_insert("scale", frame=f)
    linear(ob)
    return ob


if args.view == "anim":
    F0, F1 = 1, 216
    emis = lambda m: m.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"]
    # 1) sound waves arrive at the microphone
    for k, m in enumerate(reversed(ARC_MATS)):
        pairs = [(F0, 0.15)]
        for rep_ in range(3):
            t = 6 + 7 * k + 20 * rep_
            pairs += [(t - 4, 0.15), (t, 6.0), (t + 9, 0.15)]
        keys(emis(m), "default_value", pairs)
    # 2) analog signal: mic -> preamp -> ADC input pin
    ORANGE, CYAN, GREEN = (1.0, 0.5, 0.1), (0.2, 0.75, 1.0), (0.2, 1.0, 0.45)
    dot([(MX + 0.49, MY), (PX - 0.3, MY)], 34, 46, ORANGE)
    dot([(PX + 0.3, MY - 0.25), (PX + 0.3, 1.2), (PIN_X[1], 1.2), (PIN_X[1], pin_y_lo)], 48, 70, ORANGE)
    # 3) the chip converts: the die lights up
    keys(emis(DIE_MAT), "default_value", [(F0, 0.04), (68, 0.04), (86, 1.6), (110, 0.9), (F1, 0.35)])
    # 4) eight digital bits to the FPGA
    for k in range(8):
        px = PIN_X[5 + k]; yk = 1.02 - 0.075 * k; tx = FX - 0.75 + 0.1 * k
        for wave in range(3):
            s0 = 88 + 2 * (k % 3) + 13 * wave
            dot([(px, pin_y_lo), (px, yk), (tx, yk), (tx, FY + FS / 2 + 0.06)], s0, s0 + 20, CYAN, r=0.03)
    # 5) filtered audio over UART to the ESP32
    for k in range(3):
        y = FY + 0.2 - 0.2 * k
        for wave in range(2):
            s0 = 136 + 3 * k + 12 * wave
            dot([(FX + FS / 2 + 0.06, y), (EX - EL / 2, y)], s0, s0 + 14, CYAN, r=0.03)
    # 6) the decision travels to the "ON" LED, which switches on
    dot([(EX + 0.4, EY - EW / 2), (EX + 0.4, LY + 0.5), (LED_X, LY + 0.5), (LED_X, LY + 0.1)], 168, 190, GREEN)
    keys(emis(M_LED_ON), "default_value", [(F0, 0.0), (189, 0.0), (193, 70.0), (200, 45.0)])
    keys(LED_LIGHT, "energy", [(F0, 0.0), (189, 0.0), (193, 14.0), (200, 9.0)])
    # camera: starts close on the microphone, pulls back to the whole board
    aim = bpy.data.objects.new("aim", None)
    col.objects.link(aim)
    cam.rotation_euler = (0, 0, 0)
    con = cam.constraints.new("TRACK_TO")
    con.target, con.track_axis, con.up_axis = aim, "TRACK_NEGATIVE_Z", "UP_Y"
    cam_d.dof.focus_object = aim
    cam_d.dof.aperture_fstop = 0.9
    for f, c, a in ((F0, (-7.2, -8.5, 6.0), (-3.4, 1.7, 0.0)),
                    (72, (-3.6, -10.0, 7.6), (0.4, 1.3, 0.0)),
                    (150, (-1.6, -13.5, 11.0), (0.9, -0.5, 0.0)),
                    (F1, (-3.4, -17.0, 14.5), (0.0, -0.25, 0.0))):
        cam.location = c; cam.keyframe_insert("location", frame=f)
        aim.location = a; aim.keyframe_insert("location", frame=f)

# ---------------------------------------------------------------------- render
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = args.samples
scene.cycles.use_adaptive_sampling = True
scene.cycles.adaptive_threshold = 0.02
scene.cycles.use_denoising = True
scene.cycles.max_bounces = 8
scene.cycles.sample_clamp_indirect = 8
scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
scene.render.resolution_percentage = args.scale
scene.view_settings.view_transform = "AgX"
try:
    scene.view_settings.look = "AgX - Medium High Contrast"
except TypeError:
    pass
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = os.path.abspath(args.out)

# soft glow on the lit LED / highlights
scene.use_nodes = True
nt = scene.node_tree
rl = nt.nodes.get("Render Layers") or nt.nodes.new("CompositorNodeRLayers")
comp = nt.nodes.get("Composite") or nt.nodes.new("CompositorNodeComposite")
glare = nt.nodes.new("CompositorNodeGlare")
glare.glare_type = "FOG_GLOW"
glare.quality = "HIGH"
glare.threshold = 1.6
glare.size = 7
glare.mix = -0.55
nt.links.new(rl.outputs["Image"], glare.inputs["Image"])
nt.links.new(glare.outputs["Image"], comp.inputs["Image"])

if args.save:
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.save))
if args.view == "anim":
    scene.render.resolution_x, scene.render.resolution_y = 1280, 720
    scene.render.fps = 24
    scene.frame_start, scene.frame_end = args.frames
    scene.render.filepath = os.path.join(os.path.abspath(args.out), "f_")
    scene.render.use_overwrite = False            # re-running the command resumes where it stopped
    scene.render.use_persistent_data = True
    bpy.ops.render.render(animation=True)
else:
    bpy.ops.render.render(write_still=True)
print("RENDERED", scene.render.filepath)
