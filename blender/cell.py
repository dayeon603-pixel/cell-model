"""
Eukaryotic animal cell - procedural sculpt for Cycles.

Scale: 1 Blender unit = 1 um. Cell ~20 um across, nucleus ~6 um,
mitochondria 1-4 um long, lysosomes 0.1-1.2 um. Proportions follow a
generic mammalian cell rather than a diagram.
"""
import bpy, bmesh, math, random
from mathutils import Vector, Euler

random.seed(20260906)

# ---------------------------------------------------------------- scene reset
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# ---------------------------------------------------------------- palette
# Deliberately tonal: one cool ground, one violet, one warm accent.
PAL = {
    "membrane":  (0.38, 0.50, 0.62, 1),
    "cytosol":   (0.70, 0.74, 0.80, 1),
    "envelope":  (0.30, 0.24, 0.42, 1),
    "chromatin": (0.20, 0.14, 0.32, 1),
    "nucleolus": (0.11, 0.07, 0.19, 1),
    "er":        (0.40, 0.26, 0.36, 1),
    "ribosome":  (0.16, 0.12, 0.18, 1),
    "golgi":     (0.52, 0.32, 0.15, 1),
    "mito_out":  (0.26, 0.36, 0.32, 1),
    "mito_in":   (0.18, 0.30, 0.26, 1),
    "lyso":      (0.40, 0.18, 0.17, 1),
    "vesicle":   (0.36, 0.44, 0.54, 1),
}

def mat(name, rgba, rough=0.42, sss=0.0, alpha=1.0, transmission=0.0, sheen=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    def put(key, val):
        try:
            b.inputs[key].default_value = val
        except (KeyError, TypeError):
            pass
    put("Base Color", rgba)
    put("Roughness", rough)
    put("Metallic", 0.0)
    put("IOR", 1.42)
    if sss:
        put("Subsurface Weight", sss)
        try:
            b.inputs["Subsurface Radius"].default_value = (0.9, 0.6, 0.6)
        except (KeyError, TypeError):
            pass
    if alpha < 1.0:
        put("Alpha", alpha)
        m.blend_method = 'BLEND' if hasattr(m, "blend_method") else m.blend_method
    if transmission:
        put("Transmission Weight", transmission)
    if sheen:
        put("Sheen Weight", sheen)
    return m

MATS = {k: None for k in PAL}
def M(key):
    if MATS[key] is None:
        opts = {}
        if key == "membrane":
            opts = dict(rough=0.34, sss=0.45, alpha=1.0, sheen=0.25)
        elif key == "envelope":
            opts = dict(rough=0.36, sss=0.40)
        elif key == "chromatin":
            opts = dict(rough=0.62, sss=0.55)
        elif key == "nucleolus":
            opts = dict(rough=0.70, sss=0.30)
        elif key == "er":
            opts = dict(rough=0.40, sss=0.35)
        elif key in ("mito_out",):
            opts = dict(rough=0.26, sss=0.15, alpha=0.42, transmission=0.25)
        elif key in ("mito_in",):
            opts = dict(rough=0.48, sss=0.25)
        elif key == "lyso":
            opts = dict(rough=0.36, sss=0.40)
        elif key == "vesicle":
            opts = dict(rough=0.30, sss=0.25)
        elif key == "cytosol":
            opts = dict(rough=0.5, alpha=0.10, transmission=0.5)
        MATS[key] = mat(key, PAL[key], **opts)
    return MATS[key]

def link(o):
    scene.collection.objects.link(o)
    return o

def new_mesh(name, bm):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    return link(o)

def shade_smooth(o):
    for p in o.data.polygons:
        p.use_smooth = True

def subsurf(o, levels=2, render=3):
    m = o.modifiers.new("subsurf", 'SUBSURF')
    m.levels = levels
    m.render_levels = render
    return m

def displace(o, size=1.6, strength=0.25, ttype='CLOUDS', depth=3, seed=0):
    """Organic surface noise - this is what replaces hand sculpting."""
    tex = bpy.data.textures.new(o.name + "_disp", type=ttype)
    if ttype == 'CLOUDS':
        tex.noise_scale = size
        tex.noise_depth = depth
        tex.noise_basis = 'VORONOI_F2_F1' if seed % 2 else 'BLENDER_ORIGINAL'
    m = o.modifiers.new("disp", 'DISPLACE')
    m.texture = tex
    m.strength = strength
    m.mid_level = 0.5
    return m

# ---------------------------------------------------------------- geometry
def ico(name, r, subd=5, loc=(0, 0, 0)):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subd, radius=r)
    o = new_mesh(name, bm)
    o.location = loc
    shade_smooth(o)
    return o

CELL_R = 10.0
NUC = Vector((-2.0, -0.6, 0.8))

# --- plasma membrane: an open cut shell, so the interior reads directly ----
# A wedge is omitted at build time rather than booleaned out - cleaner topology
# and a real cut edge once solidified.
CUT_B, CUT_A = math.radians(10), math.radians(-108)
SPAN = 2 * math.pi - (CUT_B - CUT_A)

def surf_r(th, ph):
    """Low-frequency lobes only - high-frequency noise reads as crumpled foil."""
    return CELL_R * (1
        + 0.085 * math.sin(th * 2.0 + 1.2) * math.sin(ph * 1.7 + 0.6)
        + 0.050 * math.sin(th * 3.1 + 2.4) * math.sin(ph * 2.6 + 1.9)
        + 0.022 * math.sin(th * 4.7 + 0.4) * math.sin(ph * 3.9 + 2.7))

bm = bmesh.new()
us, vs = 150, 84
grid = []
for i in range(us + 1):
    row = []
    th = CUT_B + (i / us) * SPAN
    for j in range(vs + 1):
        ph = 0.0008 + (j / vs) * (math.pi - 0.0016)
        r = surf_r(th, ph)
        row.append(bm.verts.new((
            r * math.sin(ph) * math.cos(th),
            r * math.sin(ph) * math.sin(th),
            r * math.cos(ph))))
    grid.append(row)
for i in range(us):
    for j in range(vs):
        bm.faces.new((grid[i][j], grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1]))
cell = new_mesh("plasma_membrane", bm)
shade_smooth(cell)
sol = cell.modifiers.new("thick", 'SOLIDIFY')
sol.thickness = 0.26
sol.offset = -1.0
sol.use_rim = True
subsurf(cell, 1, 2)
cell.data.materials.append(M("membrane"))

# --- nucleus: large, slightly irregular, textured chromatin ----------------
# ~6.4 um across against a 20 um cell - the proportion a real nucleus has.
chrom = ico("chromatin", 3.15, subd=6, loc=NUC)
displace(chrom, size=1.1, strength=0.30, seed=3)
displace(chrom, size=0.35, strength=0.12, seed=4)
chrom.data.materials.append(M("chromatin"))

env = ico("nuclear_envelope", 3.34, subd=6, loc=NUC)
displace(env, size=1.1, strength=0.30, seed=3)
env.data.materials.append(M("envelope"))

nucleolus = ico("nucleolus", 1.05, subd=4, loc=NUC + Vector((0.9, 0.4, 0.5)))
displace(nucleolus, size=0.6, strength=0.16, seed=5)
nucleolus.data.materials.append(M("nucleolus"))

# nuclear pores: rings seated in the envelope
pore_mat = M("envelope")
pores = []
for i in range(64):
    y = 1 - 2 * (i + 0.5) / 64
    rad = math.sqrt(max(0.0, 1 - y * y))
    th = math.pi * (1 + 5 ** 0.5) * i
    d = Vector((math.cos(th) * rad, y, math.sin(th) * rad))
    if d.x > 0.35:           # keep the camera-facing hemisphere legible
        continue
    bpy.ops.mesh.primitive_torus_add(
        major_radius=0.19, minor_radius=0.055,
        location=NUC + d * 3.36, major_segments=16, minor_segments=8)
    t = bpy.context.object
    t.rotation_mode = 'QUATERNION'
    t.rotation_quaternion = d.to_track_quat('Z', 'Y')
    t.data.materials.append(pore_mat)
    shade_smooth(t)
    pores.append(t)

# --- rough ER: continuous with the envelope, folded cisternae --------------
er_objs = []
for k, (rad, th0, arc, h, lift) in enumerate([
        (4.05, 2.05, 1.55, 1.25, -2.4),
        (4.62, 1.88, 1.62, 1.30, -1.0),
        (5.16, 2.10, 1.50, 1.20,  0.5),
        (5.62, 1.92, 1.42, 1.10,  2.0),
        (4.40, 2.85, 1.30, 1.05,  1.2),
        (4.28, 3.55, 1.45, 1.20, -1.6),
        (4.95, 3.70, 1.38, 1.15,  0.9),
        (5.48, 3.30, 1.30, 1.05, -0.4),
        (4.70, 1.30, 1.20, 1.00,  2.6)]):
    bm = bmesh.new()
    us, vs = 64, 14
    verts = []
    for i in range(us + 1):
        row = []
        u = i / us
        for j in range(vs + 1):
            v = j / vs
            th = th0 + (u - 0.5) * arc
            rr = rad + 0.20 * math.sin(u * math.pi * 5 + k) + 0.10 * math.sin(v * math.pi * 3)
            z = lift + (v - 0.5) * 2 * h + 0.22 * math.sin(u * math.pi * 4 + k)
            row.append(bm.verts.new((
                NUC.x + math.cos(th) * rr,
                NUC.y + math.sin(th) * rr,
                NUC.z + z)))
        verts.append(row)
    for i in range(us):
        for j in range(vs):
            bm.faces.new((verts[i][j], verts[i + 1][j], verts[i + 1][j + 1], verts[i][j + 1]))
    o = new_mesh("rough_ER_%d" % k, bm)
    shade_smooth(o)
    s = o.modifiers.new("thick", 'SOLIDIFY')
    s.thickness = 0.10
    subsurf(o, 1, 2)
    o.data.materials.append(M("er"))
    er_objs.append(o)

# ribosomes studding the ER - merged into a single mesh for reliability
def stud_ribosomes(objs):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    bm = bmesh.new()
    made = 0
    for ob in objs:
        ev = ob.evaluated_get(depsgraph)
        me = ev.to_mesh()
        for k, v in enumerate(me.vertices):
            if k % 7:
                continue
            co = ob.matrix_world @ v.co
            nrm = (ob.matrix_world.to_3x3() @ v.normal).normalized()
            if (co - NUC).normalized().dot(nrm) < 0.15:
                continue
            p = co + nrm * 0.075
            bmesh.ops.create_icosphere(
                bm, subdivisions=1, radius=random.uniform(0.052, 0.082),
                matrix=__import__("mathutils").Matrix.Translation(p))
            made += 1
        ev.to_mesh_clear()
    o = new_mesh("ribosomes", bm)
    shade_smooth(o)
    o.data.materials.append(M("ribosome"))
    print("RIBOSOMES", made)
    return o

stud_ribosomes(er_objs)

# --- Golgi: rounded elliptical cisternae, cis face narrow -> trans wide ----
GOL = Vector((3.4, 1.6, 2.2))
for k in range(6):
    w = 1 - k * 0.07
    bm = bmesh.new()
    us, vs = 56, 22
    verts = []
    for i in range(us + 1):
        if i == us:
            verts.append(verts[0])                  # weld the seam
            break
        row = []
        u = i / us
        for j in range(vs + 1):
            v = j / vs
            a = 2 * math.pi * u                     # around the rim
            rad = v                                  # 0 centre -> 1 rim
            # elliptical disc, thinned toward the rim so edges round off
            x = math.cos(a) * rad * 2.10 * w
            y = math.sin(a) * rad * 1.35 * w
            bulge = math.sqrt(max(0.0, 1 - rad * rad)) * 0.085
            z = k * 0.44 - 1.1 + 0.20 * (rad * rad) + bulge
            row.append(bm.verts.new((x, y, z)))
        verts.append(row)
    for i in range(us):
        for j in range(vs):
            bm.faces.new((verts[i][j], verts[i + 1][j], verts[i + 1][j + 1], verts[i][j + 1]))
    o = new_mesh("golgi_%d" % k, bm)
    o.location = GOL
    o.rotation_euler = Euler((0.30, 0.30, -0.55), 'XYZ')
    shade_smooth(o)
    bpy.context.view_layer.objects.active = o
    s_ = o.modifiers.new("thick", 'SOLIDIFY')
    s_.thickness = 0.13
    s_.offset = 0.0
    subsurf(o, 2, 3)
    o.data.materials.append(M("golgi"))

# --- mitochondria: outer body plus a real folded cristae ribbon ------------
def mitochondrion(loc, rot, scale=1.0):
    bm = bmesh.new()
    us, vs = 40, 20
    L, R = 2.6, 0.62
    verts = []
    for i in range(us + 1):
        row = []
        u = i / us
        rr = R * max(1e-3, math.sin(math.pi * u) ** 0.42)
        for j in range(vs + 1):
            a = 2 * math.pi * j / vs
            row.append(bm.verts.new((
                (u - 0.5) * L,
                math.cos(a) * rr,
                math.sin(a) * rr)))
        verts.append(row)
    for i in range(us):
        for j in range(vs):
            bm.faces.new((verts[i][j], verts[i + 1][j], verts[i + 1][j + 1], verts[i][j + 1]))
    body = new_mesh("mito_body", bm)
    shade_smooth(body)
    displace(body, size=0.8, strength=0.10, seed=7)
    body.data.materials.append(M("mito_out"))

    # cristae: a ribbon folded back and forth down the long axis
    bm = bmesh.new()
    us, vs = 90, 8
    verts = []
    for i in range(us + 1):
        row = []
        u = i / us
        w = 0.42 * math.sin(math.pi * min(max(u, 0.03), 0.97))
        fold = 0.30 * math.sin(u * math.pi * 11)
        for j in range(vs + 1):
            v = j / vs
            row.append(bm.verts.new((
                (u - 0.5) * L * 0.92,
                (v - 0.5) * 2 * w,
                fold)))
        verts.append(row)
    for i in range(us):
        for j in range(vs):
            bm.faces.new((verts[i][j], verts[i + 1][j], verts[i + 1][j + 1], verts[i][j + 1]))
    cr = new_mesh("mito_cristae", bm)
    shade_smooth(cr)
    s = cr.modifiers.new("thick", 'SOLIDIFY')
    s.thickness = 0.05
    cr.data.materials.append(M("mito_in"))

    for ob in (body, cr):
        ob.location = loc
        ob.rotation_euler = Euler(rot, 'XYZ')
        ob.scale = (scale, scale, scale)
    return body, cr

for loc, rot, sc in [
        ((6.2, 2.6, 2.0), (0.7, 0.4, 1.1), 1.05),
        ((-5.4, 3.2, 3.0), (-0.5, 1.1, 0.4), 0.92),
        ((4.2, -4.4, -2.8), (1.2, -0.6, 0.2), 1.00),
        ((-6.3, -2.2, -1.4), (0.3, 0.9, -0.8), 0.88),
        ((1.0, 5.6, -3.2), (1.0, 0.2, 0.5), 0.95),
        ((-2.4, -5.4, 3.6), (-0.9, 0.5, 0.9), 1.02),
        ((6.6, 0.4, -3.8), (0.2, -1.2, 0.6), 0.90),
        ((2.4, -2.0, 6.0), (0.9, 0.3, -0.4), 0.85),
        ((-3.8, 5.2, 0.6), (-0.3, 0.8, 1.2), 0.98)]:
    mitochondrion(Vector(loc), rot, sc)

# --- lysosomes and transport vesicles --------------------------------------
for i, loc in enumerate([(5.0, 1.2, 4.4), (-4.2, -3.4, -4.0), (2.0, -6.0, 1.0),
                         (-1.0, 4.2, 4.6), (6.0, -2.0, -0.8), (-6.6, 1.0, -2.0),
                         (0.4, -4.2, -5.0)]):
    o = ico("lysosome_%d" % i, random.uniform(0.34, 0.55), subd=4, loc=Vector(loc))
    displace(o, size=0.5, strength=0.10, seed=10 + i)
    o.data.materials.append(M("lyso"))

for i in range(34):
    while True:
        p = Vector((random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(-1, 1)))
        if 0.42 < p.length < 0.94:
            break
    p = p.normalized() * random.uniform(4.2, 8.8)
    if (p - NUC).length < 3.8:
        continue
    o = ico("vesicle_%d" % i, random.uniform(0.11, 0.24), subd=3, loc=p)
    o.data.materials.append(M("vesicle"))

# ---------------------------------------------------------------- world
world = bpy.data.worlds.new("studio")
scene.world = world
world.use_nodes = True
wt = world.node_tree
for n in list(wt.nodes):
    wt.nodes.remove(n)
out_node = wt.nodes.new("ShaderNodeOutputWorld")
mix      = wt.nodes.new("ShaderNodeMixShader")
lp       = wt.nodes.new("ShaderNodeLightPath")
bg_cam   = wt.nodes.new("ShaderNodeBackground")   # what the camera sees
bg_lit   = wt.nodes.new("ShaderNodeBackground")   # what lights the scene
bg_cam.inputs[0].default_value = (0.965, 0.970, 0.980, 1)
bg_cam.inputs[1].default_value = 1.0
bg_lit.inputs[0].default_value = (0.80, 0.84, 0.90, 1)
bg_lit.inputs[1].default_value = 0.45
wt.links.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
wt.links.new(bg_lit.outputs[0], mix.inputs[1])
wt.links.new(bg_cam.outputs[0], mix.inputs[2])
wt.links.new(mix.outputs[0], out_node.inputs[0])

# ---------------------------------------------------------------- lights
def area(name, loc, rot, size, energy):
    d = bpy.data.lights.new(name, type='AREA')
    d.size = size
    d.energy = energy
    o = bpy.data.objects.new(name, d)
    o.location = loc
    o.rotation_euler = Euler(rot, 'XYZ')
    return link(o)

area("key",  (18, -22, 20), (math.radians(46), 0, math.radians(40)), 20, 9000)
area("fill", (-20, -14, 6), (math.radians(74), 0, math.radians(-54)), 26, 2600)
area("rim",  (-8, 20, 14), (math.radians(-52), 0, math.radians(196)), 22, 4200)

# ---------------------------------------------------------------- camera
cam_d = bpy.data.cameras.new("cam")
cam_d.lens = 52
cam = link(bpy.data.objects.new("cam", cam_d))
cam.location = (23.0, -26.5, 15.5)
direction = Vector((0.0, 0.0, 0.0)) - Vector(cam.location)
cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
scene.camera = cam

# ---------------------------------------------------------------- render
scene.render.engine = 'CYCLES'
try:
    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type = 'METAL'
    prefs.get_devices()
    for d in prefs.devices:
        d.use = True
    scene.cycles.device = 'GPU'
except Exception as e:
    print("GPU setup skipped:", e)

scene.cycles.samples = 128
scene.cycles.use_denoising = True
scene.cycles.max_bounces = 8
scene.cycles.transmission_bounces = 6
scene.render.resolution_x = 1800
scene.render.resolution_y = 1150
scene.render.film_transparent = False
scene.render.image_settings.file_format = 'PNG'
scene.view_settings.view_transform = 'Standard'
scene.view_settings.exposure = 0.0
scene.view_settings.look = 'None'

import sys
out = "/Users/chloekang/Documents/cell-model/blender/cell_render.png"
scene.render.filepath = out
print("RENDER_START")
bpy.ops.render.render(write_still=True)
print("RENDER_DONE", out)

# also save the .blend so it can be opened and sculpted by hand
bpy.ops.wm.save_as_mainfile(filepath="/Users/chloekang/Documents/cell-model/blender/cell.blend")
print("BLEND_SAVED")

# --- decimate for the web, then export GLB -------------------------------
for ob in list(scene.objects):
    if ob.type != 'MESH':
        continue
    for m in list(ob.modifiers):
        if m.type == 'SUBSURF':
            m.render_levels = min(m.render_levels, 1)
            m.levels = min(m.levels, 1)
    d = ob.modifiers.new("dec", 'DECIMATE')
    d.ratio = 0.30
bpy.ops.object.select_all(action='SELECT')
glb = "/Users/chloekang/Documents/cell-model/cell.glb"
bpy.ops.export_scene.gltf(filepath=glb, export_format='GLB',
                          export_apply=True, export_cameras=False, export_lights=False)
import os
print("GLB_SAVED", glb, os.path.getsize(glb))
