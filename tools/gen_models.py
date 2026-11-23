"""Generate simple low-poly demo 3D models (binary glTF / .glb) for the 8 seeded exhibits.
Pure Python + numpy. Output: smms/static/models/<name>.glb      Run: python tools/gen_models.py"""
import json, math, os, struct
import numpy as np

OUT = os.path.join(os.path.dirname(__file__), "..", "smms", "static", "models")

# ---------- primitives: return (positions Nx3, normals Nx3, indices Mx3) ----------
def ellipsoid(rx, ry, rz, seg=32, rings=20):
    P, N, I = [], [], []
    for i in range(rings + 1):
        th = math.pi * i / rings
        for j in range(seg + 1):
            ph = 2 * math.pi * j / seg
            n = (math.sin(th) * math.cos(ph), math.cos(th), math.sin(th) * math.sin(ph))
            P.append((rx * n[0], ry * n[1], rz * n[2]))
            nn = (n[0] / rx, n[1] / ry, n[2] / rz); l = math.sqrt(sum(c * c for c in nn)); N.append(tuple(c / l for c in nn))
    for i in range(rings):
        for j in range(seg):
            a = i * (seg + 1) + j; b = a + seg + 1
            I += [(a, b, a + 1), (a + 1, b, b + 1)]
    return np.array(P, "f4"), np.array(N, "f4"), np.array(I, "u4")

def cylinder(r, h, seg=32, r_top=None):
    r_top = r if r_top is None else r_top
    P, N, I = [], [], []
    slope = (r - r_top) / h
    for j in range(seg + 1):
        ph = 2 * math.pi * j / seg; c, s = math.cos(ph), math.sin(ph)
        n = np.array([c, slope, s]); n /= np.linalg.norm(n)
        P += [(r * c, -h / 2, r * s), (r_top * c, h / 2, r_top * s)]; N += [tuple(n)] * 2
    for j in range(seg):
        a = 2 * j; I += [(a, a + 1, a + 2), (a + 2, a + 1, a + 3)]
    for y, ny, rr in ((h / 2, 1, r_top), (-h / 2, -1, r)):                    # caps
        base = len(P); P.append((0, y, 0)); N.append((0, ny, 0))
        for j in range(seg + 1):
            ph = 2 * math.pi * j / seg; P.append((rr * math.cos(ph), y, rr * math.sin(ph))); N.append((0, ny, 0))
        for j in range(seg):
            I.append((base, base + 1 + j, base + 2 + j) if ny > 0 else (base, base + 2 + j, base + 1 + j))
    return np.array(P, "f4"), np.array(N, "f4"), np.array(I, "u4")

def box(sx, sy, sz):
    P, N, I = [], [], []
    for axis in range(3):
        for sign in (1, -1):
            n = [0, 0, 0]; n[axis] = sign
            u, v = [(1, 2), (2, 0), (0, 1)][axis]
            base = len(P)
            for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                p = [0, 0, 0]; p[axis] = sign * (sx, sy, sz)[axis] / 2
                p[u] = a * (sx, sy, sz)[u] / 2; p[v] = b * (sx, sy, sz)[v] / 2
                P.append(tuple(p)); N.append(tuple(n))
            I += [(base, base + 1, base + 2), (base, base + 2, base + 3)] if sign > 0 else [(base, base + 2, base + 1), (base, base + 3, base + 2)]
    return np.array(P, "f4"), np.array(N, "f4"), np.array(I, "u4")

def torus(R, r, seg=36, side=16):
    P, N, I = [], [], []
    for i in range(seg + 1):
        u = 2 * math.pi * i / seg
        for j in range(side + 1):
            v = 2 * math.pi * j / side
            P.append(((R + r * math.cos(v)) * math.cos(u), r * math.sin(v), (R + r * math.cos(v)) * math.sin(u)))
            N.append((math.cos(v) * math.cos(u), math.sin(v), math.cos(v) * math.sin(u)))
    for i in range(seg):
        for j in range(side):
            a = i * (side + 1) + j; b = a + side + 1
            I += [(a, a + 1, b), (a + 1, b + 1, b)]
    return np.array(P, "f4"), np.array(N, "f4"), np.array(I, "u4")

def cone(r, h, seg=24): return cylinder(r, h, seg, r_top=0.0001)

def xf(prim, t=(0, 0, 0), rot=(0, 0, 0), s=(1, 1, 1)):
    P, N, I = prim
    rx, ry, rz = rot
    Rx = np.array([[1, 0, 0], [0, math.cos(rx), -math.sin(rx)], [0, math.sin(rx), math.cos(rx)]])
    Ry = np.array([[math.cos(ry), 0, math.sin(ry)], [0, 1, 0], [-math.sin(ry), 0, math.cos(ry)]])
    Rz = np.array([[math.cos(rz), -math.sin(rz), 0], [math.sin(rz), math.cos(rz), 0], [0, 0, 1]])
    R = Rz @ Ry @ Rx
    P2 = (P * np.array(s)) @ R.T + np.array(t)
    N2 = N @ R.T
    return P2.astype("f4"), N2.astype("f4"), I

# ---------- GLB writer ----------
def write_glb(path, parts):
    """parts: list of (prim, (r,g,b,a), metallic, roughness). One glTF mesh primitive + material each."""
    blob = bytearray(); views, accs, mats, prims = [], [], [], []
    def add(data, target):
        while len(blob) % 4: blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), "target": target}); blob.extend(data); return len(views) - 1
    for k, (prim, color, metal, rough) in enumerate(parts):
        P, N, I = prim
        vp = add(P.tobytes(), 34962); vn = add(N.tobytes(), 34962); vi = add(I.astype("u4").tobytes(), 34963)
        accs.append({"bufferView": vp, "componentType": 5126, "count": len(P), "type": "VEC3", "min": P.min(0).tolist(), "max": P.max(0).tolist()})
        accs.append({"bufferView": vn, "componentType": 5126, "count": len(N), "type": "VEC3"})
        accs.append({"bufferView": vi, "componentType": 5125, "count": int(I.size), "type": "SCALAR"})
        mats.append({"pbrMetallicRoughness": {"baseColorFactor": list(color), "metallicFactor": metal, "roughnessFactor": rough}, "doubleSided": True})
        prims.append({"attributes": {"POSITION": 3 * k, "NORMAL": 3 * k + 1}, "indices": 3 * k + 2, "material": k})
    g = {"asset": {"version": "2.0", "generator": "SMMS gen_models.py"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
         "meshes": [{"primitives": prims}], "materials": mats, "accessors": accs, "bufferViews": views, "buffers": [{"byteLength": len(blob)}]}
    js = json.dumps(g, separators=(",", ":")).encode()
    while len(js) % 4: js += b" "
    while len(blob) % 4: blob.append(0)
    total = 12 + 8 + len(js) + 8 + len(blob)
    with open(path, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total)); f.write(struct.pack("<I4s", len(js), b"JSON")); f.write(js)
        f.write(struct.pack("<I4s", len(blob), b"BIN\0")); f.write(blob)
    return os.path.getsize(path)

BRONZE = (0.72, 0.45, 0.2, 1); DARK = (0.04, 0.03, 0.03, 1); GOLD = (1.0, 0.78, 0.25, 1); WOOL = [(0.65, 0.12, 0.1, 1), (0.1, 0.1, 0.1, 1), (0.9, 0.85, 0.7, 1)]
WOOD = (0.5, 0.32, 0.18, 1); WHITE = (0.95, 0.95, 0.92, 1); SAND = (0.86, 0.7, 0.45, 1); SKY = (0.55, 0.75, 0.9, 1); NAVY = (0.12, 0.18, 0.35, 1)

def mask():
    return [(xf(ellipsoid(0.8, 1.05, 0.55), s=(1, 1, 0.8)), BRONZE, 0.9, 0.35),
            (xf(ellipsoid(0.17, 0.1, 0.1), t=(-0.33, 0.25, 0.42)), DARK, 0.1, 0.8), (xf(ellipsoid(0.17, 0.1, 0.1), t=(0.33, 0.25, 0.42)), DARK, 0.1, 0.8),
            (xf(cone(0.12, 0.45), t=(0, -0.05, 0.52), rot=(math.pi / 2 * 0.65, 0, 0)), BRONZE, 0.9, 0.35),
            (xf(box(0.45, 0.07, 0.1), t=(0, -0.5, 0.42)), DARK, 0.1, 0.8)]

def ring():
    return [(xf(torus(0.7, 0.14), rot=(math.pi / 2.4, 0, 0)), GOLD, 1.0, 0.18),
            (xf(ellipsoid(0.22, 0.16, 0.22), t=(0, 0.58, -0.35)), (0.7, 0.05, 0.15, 1), 0.2, 0.1)]

def sadu():
    cols = [WOOL[0], WOOL[1], WOOL[2], WOOL[0], WOOL[2], WOOL[1], WOOL[0]]
    parts = [(xf(box(1.7, 0.2, 0.06), t=(0, -0.8 + i * 0.27, 0)), c, 0.0, 0.95) for i, c in enumerate(cols)]
    parts += [(xf(cylinder(0.04, 2.0, 12), t=(0, 0.05, -0.08), rot=(0, 0, math.pi / 2)), WOOD, 0.0, 0.7)]
    return parts

def kandura():
    return [(xf(cylinder(0.55, 1.9, 36, r_top=0.35), t=(0, -0.1, 0)), WHITE, 0.0, 0.9),
            (xf(cylinder(0.14, 1.1, 16), t=(-0.62, 0.35, 0), rot=(0, 0, 0.9)), WHITE, 0.0, 0.9),
            (xf(cylinder(0.14, 1.1, 16), t=(0.62, 0.35, 0), rot=(0, 0, -0.9)), WHITE, 0.0, 0.9),
            (xf(torus(0.3, 0.025), t=(0, 0.78, 0.0), rot=(math.pi / 2, 0, 0)), GOLD, 0.8, 0.3),
            (xf(box(0.25, 0.5, 0.02), t=(0, 0.45, 0.33)), GOLD, 0.8, 0.3)]

def pearl():
    return [(xf(cylinder(0.7, 0.9, 32, r_top=0.55), t=(-0.3, -0.2, 0)), (0.6, 0.45, 0.25, 1), 0.0, 0.9),
            (xf(torus(0.55, 0.05), t=(-0.3, 0.27, 0)), WOOD, 0.0, 0.7),
            (xf(torus(0.2, 0.035), t=(0.85, 0.1, 0), rot=(math.pi / 2, 0, 0)), (0.3, 0.3, 0.3, 1), 0.7, 0.4),
            (xf(ellipsoid(0.14, 0.14, 0.14), t=(-0.3, 0.1, 0.1)), (0.97, 0.96, 0.92, 1), 0.3, 0.15)]

def dhow():
    return [(xf(ellipsoid(1.2, 0.35, 0.4), t=(0, -0.3, 0), s=(1, 1, 1)), WOOD, 0.0, 0.8),
            (xf(cylinder(0.04, 1.8, 12), t=(0.05, 0.55, 0)), (0.3, 0.2, 0.1, 1), 0.0, 0.8),
            (xf(box(0.04, 1.1, 0.9), t=(-0.35, 0.65, 0), rot=(0, 0, -0.25)), WHITE, 0.0, 0.95),
            (xf(cylinder(0.025, 1.2, 10), t=(0.15, 0.1, 0), rot=(0, 0, 1.2)), (0.3, 0.2, 0.1, 1), 0.0, 0.8)]

def calligraphy():
    parts = [(xf(box(1.8, 1.3, 0.08)), (0.35, 0.22, 0.1, 1), 0.2, 0.6), (xf(box(1.6, 1.1, 0.09), t=(0, 0, 0.01)), (0.93, 0.88, 0.75, 1), 0.0, 0.9)]
    for i, (x, y, w) in enumerate([(-0.4, 0.25, 0.7), (0.3, 0.1, 0.8), (-0.1, -0.15, 0.9), (0.35, -0.35, 0.5)]):
        parts.append((xf(box(w, 0.07, 0.02), t=(x, y, 0.065), rot=(0, 0, 0.04 * (i - 1.5))), GOLD, 0.9, 0.3))
    return parts

def landscape():
    return [(xf(box(1.8, 1.3, 0.08)), (0.25, 0.17, 0.1, 1), 0.2, 0.6), (xf(box(1.6, 1.1, 0.09), t=(0, 0, 0.01)), SKY, 0.0, 0.9),
            (xf(ellipsoid(1.2, 0.45, 0.05), t=(-0.2, -0.65, 0.05)), SAND, 0.0, 0.95), (xf(ellipsoid(0.9, 0.35, 0.05), t=(0.5, -0.6, 0.07)), (0.78, 0.6, 0.35, 1), 0.0, 0.95),
            (xf(ellipsoid(0.16, 0.16, 0.03), t=(0.45, 0.3, 0.06)), (1, 0.9, 0.5, 1), 0.0, 0.5)]

MODELS = {"mask": mask, "ring": ring, "sadu": sadu, "kandura": kandura, "pearl": pearl, "dhow": dhow, "calligraphy": calligraphy, "landscape": landscape}

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name, fn in MODELS.items():
        size = write_glb(os.path.join(OUT, name + ".glb"), fn())
        print(f"{name}.glb  {size / 1024:.1f} KB")
