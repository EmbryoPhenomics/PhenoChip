# Author: OpenAI / ChatGPT
# Fusion 360 script: chip-tree v42 depth-controlled internal joint spheres
# Purpose: compact folded 3D strict binary supply + balanced outlet manifold.
# v24 fixes the terminal well logic:
# - supply and outlet ports are forced to opposite sides of each well
# - tree leaves terminate at external side-access points, not at well centres
# - radial side-port stubs go from external access point to the well wall only
# - no generated channel segment intentionally goes to the centre of a well
# - side-port cross markers are off by default to avoid confusing artefacts

import traceback
import math
import adsk.core
import adsk.fusion

app = None
ui = None
handlers = []

CMD_ID = 'chip_tree_v42_1_depth_control_internal_joint_spheres'
CMD_NAME = 'chip-tree v42.1 depth-controlled internal spheres'
CMD_DESC = 'Folded 3D binary manifold with depth controls, collision-aware Z spacing, straight cylinders and internal joint spheres.'

EPS = 1e-9


def mm_to_cm(v_mm):
    return float(v_mm) / 10.0


def cm_to_mm(v_cm):
    return float(v_cm) * 10.0


def p3(p):
    return adsk.core.Point3D.create(mm_to_cm(p[0]), mm_to_cm(p[1]), mm_to_cm(p[2]))


def dist3(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)


def add_line3d(sketch, p1, p2, drawn=None, kind=''):
    if dist3(p1, p2) < EPS:
        return None
    if drawn is not None:
        key = tuple(sorted(((round(p1[0], 5), round(p1[1], 5), round(p1[2], 5)),
                            (round(p2[0], 5), round(p2[1], 5), round(p2[2], 5))))) + (kind,)
        if key in drawn:
            return None
        drawn.add(key)
    return sketch.sketchCurves.sketchLines.addByTwoPoints(p3(p1), p3(p2))


def add_circle_top(sketch, centre_xy, radius_mm):
    return sketch.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(mm_to_cm(centre_xy[0]), mm_to_cm(centre_xy[1]), 0),
        mm_to_cm(radius_mm)
    )


def add_text(sketch, text, pos_xyz, height_mm=2.0):
    try:
        txt_input = sketch.sketchTexts.createInput(text, mm_to_cm(height_mm), p3(pos_xyz))
        txt_input.setAsMultiLine(
            p3(pos_xyz),
            p3((pos_xyz[0] + 220, pos_xyz[1] - 75, pos_xyz[2])),
            adsk.core.HorizontalAlignments.LeftHorizontalAlignment,
            adsk.core.VerticalAlignments.TopVerticalAlignment,
            0
        )
        sketch.sketchTexts.add(txt_input)
    except Exception:
        pass


def set_3d_sketch(sketch):
    try:
        sketch.is3D = True
    except Exception:
        pass



def endpoint_key(p, nd=5):
    return (round(p[0], nd), round(p[1], nd), round(p[2], nd))


def vec_from_to(a, b):
    d = dist3(a, b)
    if d < EPS:
        return (0.0, 0.0, 0.0)
    return ((b[0]-a[0])/d, (b[1]-a[1])/d, (b[2]-a[2])/d)


def is_xy_axis_segment(s, e):
    same_z = abs(s[2] - e[2]) < EPS
    x_only = abs(s[1]-e[1]) < EPS and abs(s[0]-e[0]) > EPS
    y_only = abs(s[0]-e[0]) < EPS and abs(s[1]-e[1]) > EPS
    return same_z and (x_only or y_only)


def is_vertical_segment(s, e):
    return abs(s[0]-e[0]) < EPS and abs(s[1]-e[1]) < EPS and abs(s[2]-e[2]) > EPS


def segment_length(seg):
    return dist3(seg[0], seg[1])


def signed_angle_2d(v1, v2):
    # signed angle from v1 to v2 in XY plane
    cross = v1[0]*v2[1] - v1[1]*v2[0]
    dot = v1[0]*v2[0] + v1[1]*v2[1]
    return math.atan2(cross, dot)


def add_arc3d_xy(sketch, centre, start, end, drawn=None, kind=''):
    if dist3(centre, start) < EPS or dist3(centre, end) < EPS:
        return None
    v1 = (start[0]-centre[0], start[1]-centre[1], 0)
    v2 = (end[0]-centre[0], end[1]-centre[1], 0)
    sweep = signed_angle_2d(v1, v2)
    # take the smaller 90-degree-like turn, not the long way around
    if sweep > math.pi:
        sweep -= 2*math.pi
    elif sweep < -math.pi:
        sweep += 2*math.pi
    if abs(sweep) < EPS:
        return None
    try:
        return sketch.sketchCurves.sketchArcs.addByCenterStartSweep(p3(centre), p3(start), sweep)
    except Exception:
        # If Fusion rejects a 3D arc, fail gracefully.  The caller can fall back to lines.
        return None


def build_filleted_curve_network(sketch, segments, fillet_radius_mm=0.0, apply_fillets=False):
    """Draw a centreline network, optionally filleting only non-branch, non-well XY corners.

    A bend is eligible only when exactly two segments meet at the node, both are coplanar XY axis-aligned
    line segments, the turn is 90 degrees, and neither segment is a radial well stub.  T-junctions,
    well-side stubs and Z-vias are left sharp by design.
    Returns list of {curve,start,end,kind} for later sweep attempts.
    """
    curve_records = []
    drawn = set()
    if not apply_fillets or fillet_radius_mm <= EPS:
        for s, e, kind in segments:
            c = add_line3d(sketch, s, e, drawn, kind)
            if c:
                curve_records.append({'curve': c, 'start': s, 'end': e, 'kind': kind, 'type': 'line'})
        return curve_records

    # Build incidence graph.
    nodes = {}
    for idx, (s, e, kind) in enumerate(segments):
        nodes.setdefault(endpoint_key(s), []).append((idx, 's'))
        nodes.setdefault(endpoint_key(e), []).append((idx, 'e'))

    # Determine trim points at eligible nodes.
    trim = {}  # (seg_index, endpoint 's'/'e') -> new endpoint point
    arcs = []
    used_node = set()
    for k, inc in nodes.items():
        if len(inc) != 2:
            continue
        (i1, end1), (i2, end2) = inc
        s1, e1, kind1 = segments[i1]
        s2, e2, kind2 = segments[i2]
        if 'radial_side_port_stub' in kind1 or 'radial_side_port_stub' in kind2:
            continue
        if 'top_open' in kind1 or 'top_open' in kind2:
            continue
        if not is_xy_axis_segment(s1, e1) or not is_xy_axis_segment(s2, e2):
            continue
        node = s1 if end1 == 's' else e1
        # vectors from node outwards along each segment
        other1 = e1 if end1 == 's' else s1
        other2 = e2 if end2 == 's' else s2
        u1 = vec_from_to(node, other1)
        u2 = vec_from_to(node, other2)
        # must be a 90 degree turn, not a straight-through point
        dot = abs(u1[0]*u2[0] + u1[1]*u2[1] + u1[2]*u2[2])
        if dot > 1e-4:
            continue
        l1, l2 = segment_length(segments[i1]), segment_length(segments[i2])
        r = min(float(fillet_radius_mm), l1 * 0.45, l2 * 0.45)
        if r <= 0.02:
            continue
        p1 = (node[0] + u1[0]*r, node[1] + u1[1]*r, node[2] + u1[2]*r)
        p2 = (node[0] + u2[0]*r, node[1] + u2[1]*r, node[2] + u2[2]*r)
        centre = (node[0] + (u1[0]+u2[0])*r, node[1] + (u1[1]+u2[1])*r, node[2])
        trim[(i1, end1)] = p1
        trim[(i2, end2)] = p2
        arcs.append((centre, p1, p2, 'non_branch_bend_fillet'))
        used_node.add(k)

    # Draw trimmed lines.
    for idx, (s, e, kind) in enumerate(segments):
        ns = trim.get((idx, 's'), s)
        ne = trim.get((idx, 'e'), e)
        c = add_line3d(sketch, ns, ne, drawn, kind)
        if c:
            curve_records.append({'curve': c, 'start': ns, 'end': ne, 'kind': kind, 'type': 'line'})

    # Draw arcs.  If an arc fails, add a two-line chamfer rather than restoring duplicated original corner.
    for centre, a, b, kind in arcs:
        c = add_arc3d_xy(sketch, centre, a, b, drawn, kind)
        if c:
            curve_records.append({'curve': c, 'start': a, 'end': b, 'center': centre, 'kind': kind, 'type': 'arc'})
        else:
            c1 = add_line3d(sketch, a, b, drawn, kind + '_fallback_chamfer')
            if c1:
                curve_records.append({'curve': c1, 'start': a, 'end': b, 'kind': kind + '_fallback_chamfer', 'type': 'line'})
    return curve_records


def offset_plane_for_axis(comp, axis, coord_mm):
    planes = comp.constructionPlanes
    inp = planes.createInput()
    vi = adsk.core.ValueInput.createByReal(mm_to_cm(coord_mm))
    if axis == 'x':
        inp.setByOffset(comp.yZConstructionPlane, vi)
    elif axis == 'y':
        inp.setByOffset(comp.xZConstructionPlane, vi)
    else:
        inp.setByOffset(comp.xYConstructionPlane, vi)
    return planes.add(inp)


def create_cylinder_temp_body(start, end, diameter_mm):
    """Return a temporary cylindrical BRep between two mm-coordinate points."""
    if dist3(start, end) < EPS or diameter_mm <= EPS:
        return None
    mgr = adsk.fusion.TemporaryBRepManager.get()
    return mgr.createCylinderOrCone(
        p3(start),
        mm_to_cm(diameter_mm / 2.0),
        p3(end),
        mm_to_cm(diameter_mm / 2.0)
    )


def create_sphere_temp_body(center, diameter_mm):
    """Return a temporary spherical BRep at a channel joint.

    The sphere diameter matches the channel diameter.  It is used as a robust
    substitute for failed automatic fillets at corners and T-junctions: the
    straight cylindrical channel chunks meet/overlap the sphere, creating a
    continuous-looking editable junction without asking Fusion to sweep a
    multi-branch path.
    """
    if diameter_mm <= EPS:
        return None
    mgr = adsk.fusion.TemporaryBRepManager.get()
    return mgr.createSphere(p3(center), mm_to_cm(diameter_mm / 2.0))


def add_temp_body_to_component(comp, temp_body, base_feature=None, name_hint='channel_body'):
    """Add a temporary BRep body to the component.

    In Fusion's parametric/part environment, adding temporary BRep bodies often requires
    an active BaseFeature.  v26 failed because it called bRepBodies.add(tempBody) directly,
    which produced: "A valid targetBaseFeature is required" / "Environment is not supported".
    """
    real_body = None
    try:
        if base_feature is not None:
            real_body = comp.bRepBodies.add(temp_body, base_feature)
        else:
            real_body = comp.bRepBodies.add(temp_body)
    except TypeError:
        # Some Fusion builds expose only the single-argument form.
        real_body = comp.bRepBodies.add(temp_body)
    if real_body:
        try:
            real_body.name = name_hint
        except Exception:
            pass
    return real_body


def arc_points_xy(center, start, end, diameter_mm=1.0, min_segments=3, max_segments=24):
    """Approximate a coplanar XY fillet arc as points for robust cylinder creation.

    v27 used a fixed 12 segments.  For small fillets and 1 mm channels this can create
    very short cylinder chunks that Fusion sometimes rejects or that are visually lost.
    v29 chooses a segment length relative to the channel diameter so the elbows are
    made from fewer, longer overlapping cylinders.
    """
    if not center:
        return [start, end]
    r = dist3(center, start)
    if r < EPS:
        return [start, end]
    a0 = math.atan2(start[1] - center[1], start[0] - center[0])
    a1 = math.atan2(end[1] - center[1], end[0] - center[0])
    sweep = a1 - a0
    if sweep > math.pi:
        sweep -= 2 * math.pi
    elif sweep < -math.pi:
        sweep += 2 * math.pi
    arc_len = abs(sweep) * r
    target = max(0.25, float(diameter_mm) * 0.45)
    n = int(math.ceil(arc_len / target)) if target > EPS else min_segments
    n = max(int(min_segments), min(int(max_segments), n))
    pts = []
    for i in range(n + 1):
        t = i / float(n)
        a = a0 + sweep * t
        pts.append((center[0] + math.cos(a) * r, center[1] + math.sin(a) * r, center[2]))
    return pts


def create_channel_bodies_direct(comp, curve_records, diameter_mm, body_overlap_mm=0.0, create_joint_spheres=True, joint_sphere_diameter_mm=None, node_spheres_every_endpoint=True, node_cutback_fraction=0.0, no_sphere_keys=None, max_count=20000):
    """Create cylindrical channel bodies from straight path coordinates only.

    v32 deliberately does not create true fillets.  Straight cylinders form the
    channel limbs, and optional spheres are placed at shared endpoints/corners
    to make intersections robust and editable.  This matches the manual Fusion
    workaround: a sphere with diameter equal to the channel placed at the failed
    fillet/joint location.
    """
    made = 0
    made_lines = 0
    made_spheres = 0
    skipped_arcs = 0
    failed = 0
    reasons = []
    if diameter_mm <= EPS:
        return made, failed, ['Channel diameter is zero or negative.'], {'lines': 0, 'joint_spheres': 0, 'arcs_skipped': 0, 'overlap_mm': 0}

    base_feature = None
    editing_base_feature = False
    try:
        base_feature = comp.features.baseFeatures.add()
        try:
            base_feature.name = 'chip-tree v41 cylinders plus internal TRUE node spheres base feature'
        except Exception:
            pass
        base_feature.startEdit()
        editing_base_feature = True
    except Exception as e:
        base_feature = None
        if len(reasons) < 8:
            reasons.append('Could not create/start BaseFeature: {}'.format(e))

    # Endpoints in this set deliberately do NOT receive spheres.
    # v41 excludes top-open inlet/outlet surface ports and the well-wall termination
    # points of radial side-port stubs, while retaining internal corners/junctions.
    no_sphere_keys = set(no_sphere_keys or [])

    # Count endpoints in the line network.  Shared endpoints become joint sphere
    # candidates.  We also keep an averaged coordinate for each rounded key so
    # spheres land exactly where the sketch joint is.
    line_endpoint_counts = {}
    line_endpoint_sums = {}
    endpoint_kinds = {}
    for rec in curve_records[:max_count]:
        if rec.get('type') == 'arc' or 'tiny_sideport_tick' in rec.get('kind', ''):
            continue
        kind = rec.get('kind', '')
        for pt in (rec['start'], rec['end']):
            k = endpoint_key(pt)
            line_endpoint_counts[k] = line_endpoint_counts.get(k, 0) + 1
            sx, sy, sz = line_endpoint_sums.get(k, (0.0, 0.0, 0.0))
            line_endpoint_sums[k] = (sx + pt[0], sy + pt[1], sz + pt[2])
            endpoint_kinds.setdefault(k, set()).add(kind)

    # Decide which endpoints receive a visible node sphere.  Forcing every endpoint is
    # useful because straight cylinder chunks otherwise have flat caps at isolated bends
    # and side-port junctions.  The sphere is made visible by cutting the cylinders back
    # from the node before placing the sphere, instead of burying the sphere inside the
    # cylinder overlap.
    node_keys = set()
    if create_joint_spheres:
        for kk, cc in line_endpoint_counts.items():
            if kk in no_sphere_keys:
                continue
            if node_spheres_every_endpoint or cc >= 2:
                kinds = endpoint_kinds.get(kk, set())
                if not all('tiny_sideport_tick' in knd for knd in kinds):
                    node_keys.add(kk)

    def adjusted_for_nodes_and_overlap(a, b):
        length = dist3(a, b)
        if length < EPS:
            return a, b
        u = vec_from_to(a, b)
        a2 = a
        b2 = b
        sphere_d = float(joint_sphere_diameter_mm) if joint_sphere_diameter_mm is not None and float(joint_sphere_diameter_mm) > 0 else diameter_mm
        # Cut back by a fraction of the channel diameter.  This makes the joint sphere
        # genuinely visible and avoids the mathematical problem where a same-diameter
        # sphere at the intersection is swallowed inside overlapping cylinders.
        cut = max(0.0, float(node_cutback_fraction)) * diameter_mm
        cut = min(cut, length * 0.35, sphere_d * 0.9)
        if endpoint_key(a) in node_keys and cut > EPS:
            a2 = (a[0] + u[0] * cut, a[1] + u[1] * cut, a[2] + u[2] * cut)
        elif body_overlap_mm > EPS and line_endpoint_counts.get(endpoint_key(a), 0) >= 2:
            ov = min(max(0.0, float(body_overlap_mm)), length * 0.20, max(0.0, diameter_mm * 0.20))
            a2 = (a[0] - u[0] * ov, a[1] - u[1] * ov, a[2] - u[2] * ov)
        if endpoint_key(b) in node_keys and cut > EPS:
            b2 = (b[0] - u[0] * cut, b[1] - u[1] * cut, b[2] - u[2] * cut)
        elif body_overlap_mm > EPS and line_endpoint_counts.get(endpoint_key(b), 0) >= 2:
            ov = min(max(0.0, float(body_overlap_mm)), length * 0.20, max(0.0, diameter_mm * 0.20))
            b2 = (b[0] + u[0] * ov, b[1] + u[1] * ov, b[2] + u[2] * ov)
        # If a segment is too short to cut back from both ends, leave it unchanged rather
        # than deleting it.  This is common for short well side-port stubs.
        if dist3(a2, b2) < max(0.01, diameter_mm * 0.08):
            return a, b
        return a2, b2

    def add_one(a, b, name):
        nonlocal made, made_lines, made_spheres, failed, reasons
        if dist3(a, b) < max(0.01, diameter_mm * 0.02):
            return
        a_body, b_body = adjusted_for_nodes_and_overlap(a, b)
        try:
            temp = create_cylinder_temp_body(a_body, b_body, diameter_mm)
            if not temp:
                failed += 1
                if len(reasons) < 8:
                    reasons.append('{}: TemporaryBRep returned no body'.format(name))
                return
            body = add_temp_body_to_component(comp, temp, base_feature, name)
            if body:
                made += 1
                made_lines += 1
            else:
                failed += 1
                if len(reasons) < 8:
                    reasons.append('{}: bRepBodies.add returned no body'.format(name))
        except Exception as e:
            failed += 1
            if len(reasons) < 8:
                reasons.append('{}: {}'.format(name, e))

    def add_joint_sphere(k, count, idx):
        nonlocal made, made_spheres, failed, reasons
        if k not in node_keys:
            return
        sx, sy, sz = line_endpoint_sums[k]
        c = (sx / float(count), sy / float(count), sz / float(count))
        sphere_d = float(joint_sphere_diameter_mm) if joint_sphere_diameter_mm is not None and float(joint_sphere_diameter_mm) > 0 else diameter_mm
        try:
            temp = create_sphere_temp_body(c, sphere_d)
            if not temp:
                raise RuntimeError('TemporaryBRepManager.createSphere returned no body')
            body = add_temp_body_to_component(comp, temp, base_feature, 'channel_node_TRUE_sphere_{:04d}_D{:.3f}mm'.format(idx, sphere_d))
            if body:
                made += 1
                made_spheres += 1
            else:
                raise RuntimeError('bRepBodies.add returned no true sphere body')
        except Exception as e:
            failed += 1
            if len(reasons) < 12:
                reasons.append('true_node_sphere_{:04d}: true sphere failed: {}'.format(idx, e))

    try:
        for idx, rec in enumerate(curve_records[:max_count]):
            kind = rec.get('kind', '')
            if 'tiny_sideport_tick' in kind:
                continue
            if rec.get('type') == 'arc':
                skipped_arcs += 1
                continue
            add_one(rec['start'], rec['end'], 'channel_body_line_{:04d}'.format(idx))

        if create_joint_spheres:
            for si, (k, count) in enumerate(line_endpoint_counts.items()):
                add_joint_sphere(k, count, si)
    finally:
        if editing_base_feature:
            try:
                base_feature.finishEdit()
            except Exception as e:
                if len(reasons) < 8:
                    reasons.append('BaseFeature.finishEdit failed: {}'.format(e))

    if made == 0 and not reasons:
        reasons.append('No bodies were created, but Fusion returned no error details.')
    return made, failed, reasons, {'lines': made_lines, 'joint_spheres': made_spheres, 'arcs_skipped': skipped_arcs, 'overlap_mm': max(0.0, float(body_overlap_mm)), 'node_cutback_mm': max(0.0, float(node_cutback_fraction))*diameter_mm}

def clearance_warnings(params, channel_diameter_mm):
    warnings = []
    d = float(channel_diameter_mm)
    if d <= EPS:
        return warnings
    req_gap = d + max(0.0, float(params.get('z_body_clearance_mm', 0.0)))
    min_layer_gap = min(abs(params.get('supply_layer_spacing_mm', 0)), abs(params.get('outlet_layer_spacing_mm', 0)))
    if min_layer_gap > EPS and min_layer_gap < req_gap:
        warnings.append('Z-layer centreline spacing {:.2f} mm is less than channel diameter + clearance {:.2f} mm; stacked bodies may collide.'.format(min_layer_gap, req_gap))

    supply_deepest = abs(params.get('supply_depth_mm', 0)) + max(0, int(params.get('supply_layers', 1)) - 1) * abs(params.get('supply_layer_spacing_mm', 0))
    outlet_shallowest = abs(params.get('outlet_depth_mm', 0))
    outlet_deepest = outlet_shallowest + max(0, int(params.get('outlet_layers', 1)) - 1) * abs(params.get('outlet_layer_spacing_mm', 0))
    stack_gap = outlet_shallowest - supply_deepest
    if stack_gap < req_gap:
        warnings.append('Supply and outlet depth stacks are too close: gap {:.2f} mm, required {:.2f} mm. Increase outlet first depth or enable auto Z spacing.'.format(stack_gap, req_gap))
    deepest = max(supply_deepest, outlet_deepest)
    max_depth = abs(params.get('max_channel_depth_mm', 0))
    if max_depth > EPS and deepest + d / 2.0 > max_depth:
        warnings.append('Generated channel bodies extend to about {:.2f} mm below top including radius, exceeding maximum channel depth {:.2f} mm. Increase maximum channel depth or reduce layers/diameter/clearance.'.format(deepest + d / 2.0, max_depth))

    well_gap_x = params.get('well_pitch_x_mm', 0) - 2*params.get('well_radius_mm', 0)
    well_gap_y = params.get('well_pitch_y_mm', 0) - 2*params.get('well_radius_mm', 0)
    if well_gap_x > EPS and d > well_gap_x * 0.8:
        warnings.append('Channel diameter {:.2f} mm is large compared with horizontal free gap between wells {:.2f} mm.'.format(d, well_gap_x))
    if well_gap_y > EPS and d > well_gap_y * 0.8:
        warnings.append('Channel diameter {:.2f} mm is large compared with vertical free gap between wells {:.2f} mm.'.format(d, well_gap_y))
    entry = params.get('side_entry_length_mm', 0)
    if entry > EPS and d > entry * 0.85:
        warnings.append('Channel diameter {:.2f} mm is large compared with straight side-port entry length {:.2f} mm; increase entry length or reduce diameter.'.format(d, entry))
    return warnings


def selected_dropdown_name(inputs, input_id, default=''):
    try:
        item = inputs.itemById(input_id)
        if item and item.selectedItem:
            return item.selectedItem.name
    except Exception:
        pass
    return default


def selected_well_count(inputs):
    name = selected_dropdown_name(inputs, 'well_count', '32 wells')
    try:
        return int(name.split()[0])
    except Exception:
        return 32


def valid_power2_divisors(n):
    vals = []
    r = 1
    while r <= n:
        if n % r == 0:
            vals.append(r)
        r *= 2
    return vals


def auto_compact_rows(n):
    root = math.sqrt(n)
    options = [r for r in valid_power2_divisors(n) if r <= 16]
    return min(options, key=lambda r: abs(r - root)) if options else 1


def selected_rows(inputs, n):
    name = selected_dropdown_name(inputs, 'surface_rows', 'Auto compact')
    if name.startswith('Auto'):
        return auto_compact_rows(n)
    try:
        rows = int(name.split()[0])
    except Exception:
        return auto_compact_rows(n)
    if rows < 1 or rows > n or n % rows != 0 or (rows & (rows - 1)) != 0:
        return auto_compact_rows(n)
    return rows


def selected_layers(inputs, tree_depth, input_id):
    name = selected_dropdown_name(inputs, input_id, 'Auto one layer per split')
    if name.startswith('Auto'):
        return tree_depth + 1
    try:
        v = int(name.split()[0])
    except Exception:
        return tree_depth + 1
    return max(1, min(v, tree_depth + 1))


def z_for_level(level, first_depth, layer_spacing, n_layers):
    idx = min(level, max(0, n_layers - 1))
    return -abs(first_depth) - idx * abs(layer_spacing)


def cluster_centre(indices, xy):
    xs = [xy[i][0] for i in indices]
    ys = [xy[i][1] for i in indices]
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


def split_indices_by_span(indices, xy):
    xs = [xy[i][0] for i in indices]
    ys = [xy[i][1] for i in indices]
    axis = 'x' if (max(xs) - min(xs)) >= (max(ys) - min(ys)) else 'y'
    if axis == 'x':
        ordered = sorted(indices, key=lambda i: (xy[i][0], xy[i][1]))
    else:
        ordered = sorted(indices, key=lambda i: (xy[i][1], xy[i][0]))
    mid = len(ordered) // 2
    return ordered[:mid], ordered[mid:], axis


def side_normal(side):
    if side == 'right':
        return (1.0, 0.0)
    if side == 'left':
        return (-1.0, 0.0)
    if side == 'top':
        return (0.0, 1.0)
    if side == 'bottom':
        return (0.0, -1.0)
    return (1.0, 0.0)


def opposite_side(side):
    return {'left': 'right', 'right': 'left', 'top': 'bottom', 'bottom': 'top'}.get(side, 'right')


def side_access_geometry(well_xy, side, well_radius, straight_len):
    """Return port on well wall and external access point.

    access->port is radial, perpendicular to the circular wall, and never goes to the well centre.
    """
    wx, wy = well_xy
    nx, ny = side_normal(side)
    port = (wx + nx * well_radius, wy + ny * well_radius)
    access = (wx + nx * (well_radius + max(0.0, straight_len)),
              wy + ny * (well_radius + max(0.0, straight_len)))
    return port, access


def selected_supply_side(inputs):
    name = selected_dropdown_name(inputs, 'port_orientation', 'Supply left / outlet right')
    if name.startswith('Supply right'):
        return 'right'
    if name.startswith('Supply bottom'):
        return 'bottom'
    if name.startswith('Supply top'):
        return 'top'
    return 'left'


def add_axis_manhattan(segments, start, end, kind, preferred_axis='auto'):
    if dist3(start, end) < EPS:
        return
    # Change Z first, at the current XY position.  This makes layer changes visible and explicit.
    if abs(start[2] - end[2]) > EPS:
        via = (start[0], start[1], end[2])
        if dist3(start, via) > EPS:
            segments.append((start, via, kind + '_z'))
        start = via
    if abs(start[0] - end[0]) < EPS or abs(start[1] - end[1]) < EPS:
        segments.append((start, end, kind))
        return
    if preferred_axis == 'x_first':
        mid = (end[0], start[1], start[2])
    elif preferred_axis == 'y_first':
        mid = (start[0], end[1], start[2])
    else:
        mid = (end[0], start[1], start[2]) if abs(end[0]-start[0]) >= abs(end[1]-start[1]) else (start[0], end[1], start[2])
    segments.append((start, mid, kind + '_dogleg_1'))
    segments.append((mid, end, kind + '_dogleg_2'))


def compute_binary_tree_to_side_targets(indices, target_xy, port_records, params, segments, path_lengths, route_counts, network):
    """Draw a strict binary tree to external side-access targets.

    Crucially, the tree leaf is the side-access point outside the well, not the well centre.
    The final access->port stub is then added radially to the well wall.
    """
    n_layers = params[network.lower() + '_layers']
    first_depth = params[network.lower() + '_depth_mm']
    spacing = params[network.lower() + '_layer_spacing_mm']
    root_xy = cluster_centre(indices, target_xy)
    root_z = z_for_level(0, first_depth, spacing, n_layers)
    split_records = []

    def recurse(idxs, parent_xy, parent_z, level):
        parent_pt = (parent_xy[0], parent_xy[1], parent_z)
        if len(idxs) == 1:
            i = idxs[0]
            rec = port_records[i]
            access_pt = (rec['access'][0], rec['access'][1], parent_z)
            port_pt = (rec['port'][0], rec['port'][1], parent_z)
            before = len(segments)
            # If parent is not already the access point, route to access only.  In normal
            # recursion the parent point is already the target/access, so this is zero.
            preferred = 'x_first' if rec['side'] in ('left', 'right') else 'y_first'
            add_axis_manhattan(segments, parent_pt, access_pt, network + '_terminal_route_to_external_access_NOT_well_centre', preferred)
            segments.append((access_pt, port_pt, network + '_radial_side_port_stub_to_well_wall'))
            added = sum(dist3(s, e) for s, e, _ in segments[before:])
            path_lengths[i] += added
            route_counts[i][network.lower() + '_bends_xy'] += max(0, len(segments) - before - 1)
            rec['z'] = parent_z
            return

        left, right, axis = split_indices_by_span(idxs, target_xy)
        child_level = level + 1
        child_z = z_for_level(child_level, first_depth, spacing, n_layers)
        via_pt = (parent_xy[0], parent_xy[1], child_z)
        via_len = 0.0
        if abs(child_z - parent_z) > EPS:
            segments.append((parent_pt, via_pt, network + '_vertical_via_between_folded_branch_layers'))
            via_len = abs(child_z - parent_z)

        def child_centre(child):
            if len(child) == 1:
                i = child[0]
                return target_xy[i]
            return cluster_centre(child, target_xy)

        left_xy = child_centre(left)
        right_xy = child_centre(right)
        preferred = 'x_first' if axis == 'x' else 'y_first'
        before_l = len(segments)
        add_axis_manhattan(segments, via_pt, (left_xy[0], left_xy[1], child_z), network + '_symmetric_binary_branch', preferred)
        left_added = via_len + sum(dist3(s, e) for s, e, _ in segments[before_l:])
        before_r = len(segments)
        add_axis_manhattan(segments, via_pt, (right_xy[0], right_xy[1], child_z), network + '_symmetric_binary_branch', preferred)
        right_added = via_len + sum(dist3(s, e) for s, e, _ in segments[before_r:])

        split_records.append({'network': network, 'n': len(idxs), 'level': level, 'axis': axis, 'parent': parent_xy, 'z': child_z})
        for i in left:
            path_lengths[i] += left_added
            route_counts[i][network.lower() + '_vias'] += 1 if via_len > EPS else 0
            route_counts[i][network.lower() + '_branch_levels'] += 1
        for i in right:
            path_lengths[i] += right_added
            route_counts[i][network.lower() + '_vias'] += 1 if via_len > EPS else 0
            route_counts[i][network.lower() + '_branch_levels'] += 1
        recurse(left, left_xy, child_z, child_level)
        recurse(right, right_xy, child_z, child_level)

    recurse(indices, root_xy, root_z, 0)
    return root_xy, root_z, split_records


def point_segment_distance_2d(px, py, ax, ay, bx, by):
    vx = bx - ax
    vy = by - ay
    wx = px - ax
    wy = py - ay
    c1 = vx * vx + vy * vy
    if c1 < EPS:
        return math.sqrt((px - ax) ** 2 + (py - ay) ** 2)
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / c1))
    qx = ax + t * vx
    qy = ay + t * vy
    return math.sqrt((px - qx) ** 2 + (py - qy) ** 2)


def count_well_keepout_hits(segments, wells, radius, clearance):
    # Diagnostic only.  The intended side-port stub is allowed to touch the well wall.
    hits = []
    keep = radius + clearance
    for si, (s, e, kind) in enumerate(segments):
        if 'radial_side_port_stub' in kind:
            continue
        for wi, (wx, wy) in enumerate(wells):
            d = point_segment_distance_2d(wx, wy, s[0], s[1], e[0], e[1])
            if d < keep - 1e-6:
                hits.append((si, wi, kind, d))
    return hits


def compute_layout(params):
    n = int(params['n_wells'])
    if n < 2 or (n & (n - 1)) != 0:
        raise ValueError('Well count must be a power of two and at least 2.')
    rows = int(params['rows'])
    if rows < 1 or rows > n or n % rows != 0 or (rows & (rows - 1)) != 0:
        raise ValueError('Top-surface rows must be a power-of-two divisor of the well count.')

    cols = n // rows
    tree_depth = int(round(math.log(n, 2)))
    grid_cx = params['grid_cx_mm']
    grid_cy = params['grid_cy_mm']
    pitch_x = params['well_pitch_x_mm']
    pitch_y = params['well_pitch_y_mm']
    z_top = 0.0

    well_xy = []
    for r in range(rows):
        y = grid_cy + (r - (rows - 1) / 2.0) * pitch_y
        for c in range(cols):
            x = grid_cx + (c - (cols - 1) / 2.0) * pitch_x
            well_xy.append((x, y))

    supply_side = params['supply_side']
    outlet_side = opposite_side(supply_side)
    well_radius = params['well_radius_mm']
    entry_len = params['side_entry_length_mm']

    supply_records = []
    outlet_records = []
    supply_targets = []
    outlet_targets = []
    for i, w in enumerate(well_xy):
        sport, saccess = side_access_geometry(w, supply_side, well_radius, entry_len)
        oport, oaccess = side_access_geometry(w, outlet_side, well_radius, entry_len)
        supply_records.append({'well_index': i, 'well': w, 'port': sport, 'access': saccess, 'side': supply_side, 'z': None})
        outlet_records.append({'well_index': i, 'well': w, 'port': oport, 'access': oaccess, 'side': outlet_side, 'z': None})
        supply_targets.append(saccess)
        outlet_targets.append(oaccess)

    segments = []
    supply_lengths = [0.0 for _ in range(n)]
    outlet_lengths = [0.0 for _ in range(n)]
    route_counts = [{'supply_vias': 0, 'supply_bends_xy': 0, 'supply_branch_levels': 0,
                     'outlet_vias': 0, 'outlet_bends_xy': 0, 'outlet_branch_levels': 0} for _ in range(n)]

    # Supply inlet -> supply root based on external access targets, not well centres.
    supply_root_xy = cluster_centre(list(range(n)), supply_targets)
    supply_root_z = z_for_level(0, params['supply_depth_mm'], params['supply_layer_spacing_mm'], params['supply_layers'])
    inlet_top = (params['inlet_x_mm'], params['inlet_y_mm'], z_top)
    inlet_bottom = (params['inlet_x_mm'], params['inlet_y_mm'], supply_root_z)
    segments.append((inlet_top, inlet_bottom, 'SUPPLY_top_open_inlet_drop_to_buried_layer'))
    before = len(segments)
    add_axis_manhattan(segments, inlet_bottom, (supply_root_xy[0], supply_root_xy[1], supply_root_z), 'SUPPLY_buried_inlet_to_supply_root', 'y_first')
    common_supply = dist3(inlet_top, inlet_bottom) + sum(dist3(s, e) for s, e, _ in segments[before:])
    for i in range(n):
        supply_lengths[i] += common_supply
        route_counts[i]['supply_vias'] += 1
        route_counts[i]['supply_bends_xy'] += max(0, len(segments) - before - 1)

    supply_root_xy, supply_root_z, supply_splits = compute_binary_tree_to_side_targets(
        list(range(n)), supply_targets, supply_records, params, segments, supply_lengths, route_counts, 'SUPPLY'
    )

    # Balanced outlet tree: outlet top -> outlet root -> side-access targets -> well wall stubs.
    outlet_root_xy = cluster_centre(list(range(n)), outlet_targets)
    outlet_root_z = z_for_level(0, params['outlet_depth_mm'], params['outlet_layer_spacing_mm'], params['outlet_layers'])
    outlet_top = (params['outlet_x_mm'], params['outlet_y_mm'], z_top)
    outlet_bottom = (params['outlet_x_mm'], params['outlet_y_mm'], outlet_root_z)
    segments.append((outlet_top, outlet_bottom, 'OUTLET_top_open_outlet_drop_to_buried_layer'))
    before = len(segments)
    add_axis_manhattan(segments, outlet_bottom, (outlet_root_xy[0], outlet_root_xy[1], outlet_root_z), 'OUTLET_buried_outlet_to_collection_root', 'y_first')
    common_outlet = dist3(outlet_top, outlet_bottom) + sum(dist3(s, e) for s, e, _ in segments[before:])
    for i in range(n):
        outlet_lengths[i] += common_outlet
        route_counts[i]['outlet_vias'] += 1
        route_counts[i]['outlet_bends_xy'] += max(0, len(segments) - before - 1)

    outlet_root_xy, outlet_root_z, outlet_splits = compute_binary_tree_to_side_targets(
        list(range(n)), outlet_targets, outlet_records, params, segments, outlet_lengths, route_counts, 'OUTLET'
    )

    total_lengths = [supply_lengths[i] + outlet_lengths[i] for i in range(n)]
    all_points = []
    for s, e, _ in segments:
        all_points.extend([s, e])
    for x, y in well_xy:
        all_points.append((x, y, 0))
    all_points.extend([inlet_top, outlet_top])
    xs = [p[0] for p in all_points]
    ys = [p[1] for p in all_points]
    zs = [p[2] for p in all_points]
    well_xs = [p[0] for p in well_xy]
    well_ys = [p[1] for p in well_xy]
    keepout_hits = count_well_keepout_hits(segments, well_xy, well_radius, params.get('well_keepout_clearance_mm', 0.0))

    return {
        'segments': segments,
        'wells': well_xy,
        'supply_ports': supply_records,
        'outlet_ports': outlet_records,
        'inlet': (params['inlet_x_mm'], params['inlet_y_mm']),
        'outlet': (params['outlet_x_mm'], params['outlet_y_mm']),
        'supply_root_xy': supply_root_xy,
        'supply_root_z': supply_root_z,
        'outlet_root_xy': outlet_root_xy,
        'outlet_root_z': outlet_root_z,
        'n_wells': n,
        'rows': rows,
        'cols': cols,
        'tree_depth': tree_depth,
        'supply_layers': params['supply_layers'],
        'outlet_layers': params['outlet_layers'],
        'supply_side': supply_side,
        'outlet_side': outlet_side,
        'supply_z_layers': sorted(set(round(z_for_level(k, params['supply_depth_mm'], params['supply_layer_spacing_mm'], params['supply_layers']), 6) for k in range(tree_depth + 1)), reverse=True),
        'outlet_z_layers': sorted(set(round(z_for_level(k, params['outlet_depth_mm'], params['outlet_layer_spacing_mm'], params['outlet_layers']), 6) for k in range(tree_depth + 1)), reverse=True),
        'supply_lengths': supply_lengths,
        'outlet_lengths': outlet_lengths,
        'total_lengths': total_lengths,
        'route_counts': route_counts,
        'split_records': supply_splits + outlet_splits,
        'keepout_hits': keepout_hits,
        'well_bbox': (min(well_xs), min(well_ys), max(well_xs), max(well_ys)),
        'route_bbox': (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)),
    }


class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            cmd.isRepeatable = False
            inputs = cmd.commandInputs
            units_mgr = app.activeProduct.unitsManager

            dd = inputs.addDropDownCommandInput('well_count', 'Number of wells', adsk.core.DropDownStyles.TextListDropDownStyle)
            for n in [2, 4, 8, 16, 32, 64]:
                dd.listItems.add('{} wells'.format(n), n == 32, '')
            dd.tooltip = 'Strict bifurcating design: power-of-two well counts only.'

            rows_dd = inputs.addDropDownCommandInput('surface_rows', 'Top-surface well rows', adsk.core.DropDownStyles.TextListDropDownStyle)
            for name, selected in [('Auto compact', True), ('1 row', False), ('2 rows', False), ('4 rows', False), ('8 rows', False), ('16 rows', False), ('32 rows', False)]:
                rows_dd.listItems.add(name, selected, '')
            rows_dd.tooltip = 'Folds the wells into a top-open grid. More rows reduce X and increase Y.'

            orient_dd = inputs.addDropDownCommandInput('port_orientation', 'Opposed well port orientation', adsk.core.DropDownStyles.TextListDropDownStyle)
            orient_dd.listItems.add('Supply left / outlet right', True, '')
            orient_dd.listItems.add('Supply right / outlet left', False, '')
            orient_dd.listItems.add('Supply bottom / outlet top', False, '')
            orient_dd.listItems.add('Supply top / outlet bottom', False, '')
            orient_dd.tooltip = 'Forces supply and outlet to be exactly opposite sides of each well. Final stubs are radial/perpendicular.'

            supply_layers_dd = inputs.addDropDownCommandInput('supply_layers', 'Supply buried routing layers', adsk.core.DropDownStyles.TextListDropDownStyle)
            for name, selected in [('Auto one layer per split', False), ('2 layers', False), ('3 layers', True), ('4 layers', False), ('5 layers', False), ('6 layers', False), ('7 layers', False)]:
                supply_layers_dd.listItems.add(name, selected, '')

            outlet_layers_dd = inputs.addDropDownCommandInput('outlet_layers', 'Outlet buried routing layers', adsk.core.DropDownStyles.TextListDropDownStyle)
            for name, selected in [('Auto one layer per split', False), ('2 layers', False), ('3 layers', True), ('4 layers', False), ('5 layers', False), ('6 layers', False), ('7 layers', False)]:
                outlet_layers_dd.listItems.add(name, selected, '')

            def val_input(id_, name, default_expr, tooltip=''):
                vi = adsk.core.ValueInput.createByString(default_expr)
                inp = inputs.addValueInput(id_, name, units_mgr.defaultLengthUnits, vi)
                if tooltip:
                    inp.tooltip = tooltip
                return inp

            val_input('grid_cx', 'Well grid centre X', '0 mm')
            val_input('grid_cy', 'Well grid centre Y', '0 mm')
            val_input('inlet_x', 'Top-open inlet X', '0 mm')
            val_input('inlet_y', 'Top-open inlet Y', '-18 mm')
            val_input('outlet_x', 'Top-open outlet X', '0 mm')
            val_input('outlet_y', 'Top-open outlet Y', '18 mm')
            val_input('well_pitch_x', 'Well pitch X', '8 mm')
            val_input('well_pitch_y', 'Well pitch Y', '8 mm')
            val_input('supply_depth', 'Supply first buried depth below top', '0.8 mm')
            val_input('supply_layer_spacing', 'Supply layer spacing', '0.35 mm')
            val_input('outlet_depth', 'Outlet first buried depth below top', '2.4 mm')
            val_input('outlet_layer_spacing', 'Outlet layer spacing', '0.35 mm')
            val_input('max_channel_depth', 'Maximum channel centreline depth below top', '6.0 mm', 'Deepest permitted channel centreline depth. Increase this if stacked supply/outlet layers collide.')
            val_input('z_body_clearance', 'Minimum vertical body clearance', '0.15 mm', 'Extra clearance between channel bodies on adjacent Z layers, beyond the channel diameter.')
            inputs.addBoolValueInput('auto_z_spacing', 'Auto-adjust Z spacing to avoid body collisions', True, '', True)
            val_input('well_radius', 'Well radius', '1.2 mm')
            val_input('side_entry_length', 'Straight side-port entry length', '0.8 mm', 'Length of the radial external stub outside the well wall.')
            val_input('well_keepout_clearance', 'Well keepout clearance for report', '0.05 mm', 'Report any non-stub segment whose XY projection enters well radius + this clearance.')
            val_input('inlet_radius', 'Inlet radius', '1.0 mm')
            val_input('outlet_radius', 'Outlet radius', '1.0 mm')
            val_input('channel_width', 'Supply channel width parameter', '0.4 mm')
            val_input('outlet_width_multiplier', 'Outlet channel width multiplier', '1.0')
            val_input('bend_radius', 'Bend radius parameter', '1.0 mm')
            inputs.addBoolValueInput('draw_wells', 'Draw top-open well/inlet/outlet circles', True, '', True)
            inputs.addBoolValueInput('draw_sideports', 'Draw side-port/access markers', True, '', False)
            inputs.addBoolValueInput('draw_labels', 'Add inlet/outlet and well labels', True, '', True)
            inputs.addBoolValueInput('draw_report', 'Add diagnostic routing report text', True, '', False)
            # v30: automatic fillets removed because Fusion/body generation made them misleading.
            inputs.addBoolValueInput('apply_fillets', 'Draw centreline fillets at single-channel direction changes (disabled in v30)', True, '', False)
            val_input('fillet_radius', 'Centreline bend fillet radius (ignored in v30)', '0.0 mm', 'Fillet generation is disabled in v30. Use straight bodies first; add true swept/filleted geometry later as a separate manufacturing step.')
            inputs.addBoolValueInput('create_swept_bodies', 'Create straight channel bodies', True, '', True)
            val_input('channel_diameter', 'Channel body diameter', '1.0 mm', 'Diameter of circular cylindrical channel bodies.')
            inputs.addBoolValueInput('create_joint_spheres', 'Add TRUE spherical node bodies at internal channel joints', True, '', True)
            inputs.addBoolValueInput('node_spheres_every_endpoint', 'Force true sphere at eligible internal endpoints', True, '', True)
            val_input('node_cutback_fraction', 'Cylinder cut-back at node spheres', '0.0', 'Normally keep this 0.0. True spheres are added as separate bodies and straight cylinders overlap them.')
            val_input('body_overlap', 'Body joint overlap', '0.10 mm', 'Small overlap added at shared endpoints so adjacent straight cylinders intersect their node sphere. Try 0.05-0.20 mm.')

            on_execute = CommandExecuteHandler()
            cmd.execute.add(on_execute)
            handlers.append(on_execute)
        except Exception:
            ui.messageBox('CommandCreated failed in v42:\n{}'.format(traceback.format_exc()))


class CommandExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            design = adsk.fusion.Design.cast(app.activeProduct)
            if not design:
                ui.messageBox('No active Fusion design. Open or create a design first.')
                return
            comp = design.rootComponent
            sketch = comp.sketches.add(comp.xYConstructionPlane)
            sketch.name = 'chip-tree v42.1 depth control + internal spheres'
            set_3d_sketch(sketch)
            inputs = args.command.commandInputs

            def mm(id_):
                return cm_to_mm(inputs.itemById(id_).value)

            def val(id_):
                return float(inputs.itemById(id_).value)

            def boolv(id_):
                return bool(inputs.itemById(id_).value)

            n = selected_well_count(inputs)
            rows = selected_rows(inputs, n)
            tree_depth = int(round(math.log(n, 2)))
            supply_layers = selected_layers(inputs, tree_depth, 'supply_layers')
            outlet_layers = selected_layers(inputs, tree_depth, 'outlet_layers')
            supply_side = selected_supply_side(inputs)

            # v42: depth/collision controls. Fusion bodies are circular cylinders, so two
            # vertically stacked channels require roughly one channel diameter plus any
            # requested clearance between their centrelines if their XY projections overlap.
            channel_diameter = mm('channel_diameter')
            max_channel_depth = mm('max_channel_depth')
            z_body_clearance = mm('z_body_clearance')
            auto_z_spacing = boolv('auto_z_spacing')
            supply_depth_mm = mm('supply_depth')
            supply_layer_spacing_mm = mm('supply_layer_spacing')
            outlet_depth_mm = mm('outlet_depth')
            outlet_layer_spacing_mm = mm('outlet_layer_spacing')
            if auto_z_spacing and channel_diameter > EPS:
                required_gap = channel_diameter + max(0.0, z_body_clearance)
                supply_layer_spacing_mm = max(supply_layer_spacing_mm, required_gap)
                outlet_layer_spacing_mm = max(outlet_layer_spacing_mm, required_gap)
                supply_deepest = supply_depth_mm + (max(1, supply_layers) - 1) * supply_layer_spacing_mm
                # Put the outlet stack below the supply stack by at least one body diameter + clearance.
                outlet_depth_mm = max(outlet_depth_mm, supply_deepest + required_gap)

            params = {
                'n_wells': n,
                'rows': rows,
                'supply_layers': supply_layers,
                'outlet_layers': outlet_layers,
                'supply_side': supply_side,
                'grid_cx_mm': mm('grid_cx'),
                'grid_cy_mm': mm('grid_cy'),
                'inlet_x_mm': mm('inlet_x'),
                'inlet_y_mm': mm('inlet_y'),
                'outlet_x_mm': mm('outlet_x'),
                'outlet_y_mm': mm('outlet_y'),
                'well_pitch_x_mm': mm('well_pitch_x'),
                'well_pitch_y_mm': mm('well_pitch_y'),
                'supply_depth_mm': supply_depth_mm,
                'supply_layer_spacing_mm': supply_layer_spacing_mm,
                'outlet_depth_mm': outlet_depth_mm,
                'outlet_layer_spacing_mm': outlet_layer_spacing_mm,
                'max_channel_depth_mm': max_channel_depth,
                'z_body_clearance_mm': z_body_clearance,
                'auto_z_spacing': auto_z_spacing,
                'well_radius_mm': mm('well_radius'),
                'side_entry_length_mm': mm('side_entry_length'),
                'well_keepout_clearance_mm': mm('well_keepout_clearance'),
            }
            well_radius = mm('well_radius')
            inlet_radius = mm('inlet_radius')
            outlet_radius = mm('outlet_radius')
            channel_width = mm('channel_width')
            outlet_width_multiplier = val('outlet_width_multiplier')
            bend_radius = mm('bend_radius')
            body_overlap = mm('body_overlap')
            create_joint_spheres = boolv('create_joint_spheres')
            node_spheres_every_endpoint = boolv('node_spheres_every_endpoint')
            joint_sphere_diameter = channel_diameter
            node_cutback_fraction = val('node_cutback_fraction')

            data = compute_layout(params)
            apply_fillets = False
            fillet_radius = 0.0
            curve_records = build_filleted_curve_network(sketch, data['segments'], fillet_radius, False)

            if boolv('draw_wells'):
                add_circle_top(sketch, data['inlet'], inlet_radius)
                add_circle_top(sketch, data['outlet'], outlet_radius)
                for w in data['wells']:
                    add_circle_top(sketch, w, well_radius)

            # v24: markers are off by default. When enabled, use tiny short ticks, not large crosses.
            if boolv('draw_sideports'):
                marker = max(0.08, min(0.22, well_radius * 0.14))
                for port in data['supply_ports'] + data['outlet_ports']:
                    x, y = port['port']
                    z = port['z'] if port['z'] is not None else 0
                    add_line3d(sketch, (x-marker, y, z), (x+marker, y, z), None, 'tiny_sideport_tick')

            try:
                user_params = design.userParameters
                length_units = design.unitsManager.defaultLengthUnits

                def upsert(name, expr, units, comment):
                    p = user_params.itemByName(name)
                    if p:
                        p.expression = expr
                        p.comment = comment
                    else:
                        user_params.add(name, adsk.core.ValueInput.createByString(expr), units, comment)

                upsert('chip_tree_well_count', str(data['n_wells']), '', 'Number of wells in folded binary manifold.')
                upsert('chip_tree_rows', str(data['rows']), '', 'Top-surface well rows.')
                upsert('chip_tree_cols', str(data['cols']), '', 'Top-surface well columns.')
                upsert('chip_tree_supply_channel_width', '{} mm'.format(round(channel_width, 6)), length_units, 'Intended supply channel width; centreline sketch only.')
                upsert('chip_tree_outlet_channel_width', '{} mm'.format(round(channel_width * outlet_width_multiplier, 6)), length_units, 'Intended outlet channel width; centreline sketch only.')
                upsert('chip_tree_bend_radius', '{} mm'.format(round(bend_radius, 6)), length_units, 'Suggested bend radius for downstream channel generation.')
                upsert('chip_tree_max_channel_depth', '{} mm'.format(round(max_channel_depth, 6)), length_units, 'Requested maximum centreline depth below top.')
                upsert('chip_tree_supply_layer_spacing', '{} mm'.format(round(params['supply_layer_spacing_mm'], 6)), length_units, 'Effective supply Z-layer centreline spacing.')
                upsert('chip_tree_outlet_layer_spacing', '{} mm'.format(round(params['outlet_layer_spacing_mm'], 6)), length_units, 'Effective outlet Z-layer centreline spacing.')
                upsert('chip_tree_outlet_first_depth', '{} mm'.format(round(params['outlet_depth_mm'], 6)), length_units, 'Effective outlet first buried depth below top.')
            except Exception:
                pass

            if boolv('draw_labels'):
                add_text(sketch, 'IN', (data['inlet'][0] + inlet_radius + 0.5, data['inlet'][1] + inlet_radius + 1.0, 0), 1.8)
                add_text(sketch, 'OUT', (data['outlet'][0] + outlet_radius + 0.5, data['outlet'][1] + outlet_radius + 1.0, 0), 1.8)
                for i, w in enumerate(data['wells']):
                    add_text(sketch, str(i + 1), (w[0] + well_radius + 0.25, w[1] + well_radius + 0.35, 0), 1.4)

            if boolv('create_swept_bodies'):
                no_sphere_keys = set()
                for rec in curve_records:
                    kind = rec.get('kind', '')
                    # No spheres at top-open inlet/outlet surface ports. Keep the buried end available.
                    if 'top_open_inlet_drop' in kind or 'top_open_outlet_drop' in kind:
                        no_sphere_keys.add(endpoint_key(rec['start']))
                    # No spheres at the well-wall termination of radial side-port stubs.
                    # The external access/corner end is intentionally NOT excluded.
                    if 'radial_side_port_stub_to_well_wall' in kind:
                        no_sphere_keys.add(endpoint_key(rec['end']))
                made, failed, reasons, body_stats = create_channel_bodies_direct(comp, curve_records, channel_diameter, body_overlap_mm=body_overlap, create_joint_spheres=create_joint_spheres, joint_sphere_diameter_mm=joint_sphere_diameter, node_spheres_every_endpoint=node_spheres_every_endpoint, node_cutback_fraction=node_cutback_fraction, no_sphere_keys=no_sphere_keys)
                warn = clearance_warnings(params, channel_diameter)
                try:
                    if made == 0:
                        msg = 'No cylindrical channel bodies were created. Failed chunks: {}.\n\nFirst failure reasons:\n{}'.format(failed, '\n'.join(reasons) if reasons else 'No error detail returned.')
                        ui.messageBox(msg)
                    elif failed or warn or (apply_fillets and body_stats.get('arcs_skipped', 0) > 0):
                        parts = ['Channel bodies created: {} (straight chunks {}, node spheres {}, joint overlap {:.3g} mm; cut-back {:.3g} mm). Failed chunks: {}.'.format(made, body_stats.get('lines', 0), body_stats.get('joint_spheres', 0), body_stats.get('overlap_mm', 0), body_stats.get('node_cutback_mm', 0), failed)]
                        if apply_fillets and body_stats.get('arcs_skipped', 0) > 0:
                            parts.append('Note: fillets are disabled in v30; bodies are straight cylindrical chunks only.')
                        if warn:
                            parts.append('Clearance warnings:\n' + '\n'.join(warn))
                        if failed:
                            parts.append('First failure reasons:\n' + ('\n'.join(reasons) if reasons else 'No error detail returned.'))
                        ui.messageBox('\n\n'.join(parts))
                except Exception:
                    pass

            if boolv('draw_report'):
                sl = data['supply_lengths']
                ol = data['outlet_lengths']
                tl = data['total_lengths']
                wb = data['well_bbox']
                rb = data['route_bbox']
                report = (
                    'chip-tree v42 DEPTH-CONTROLLED SIDE-PORTS + CYLINDRICAL BODIES\n'
                    'Topology: strict binary supply tree plus strict binary outlet tree on separate buried depth stacks.\n'
                    'Terminal rule: tree leaves terminate at external side-access points; only radial side-port stubs touch well walls.\n'
                    'Port orientation: supply {ss}; outlet {os}. These are exactly opposite sides of every well.\n'
                    'Top layout: {rows} x {cols}; well bbox {ww:.2f} x {wh:.2f} mm; route bbox {rw:.2f} x {rh:.2f} mm; Z span {zs:.2f} mm.\n'
                    'Supply length delta {sdelta:.6f} mm; outlet length delta {odelta:.6f} mm; total delta {tdelta:.6f} mm.\n'
                    'Well keepout hits excluding radial stubs: {kh}. If non-zero, increase pitch/entry length, change orientation, or use more rows/layers.\n'
                    'Side-port markers are off by default to avoid cross-like artefacts.'
                ).format(
                    ss=data['supply_side'], os=data['outlet_side'], rows=data['rows'], cols=data['cols'],
                    ww=wb[2]-wb[0], wh=wb[3]-wb[1], rw=rb[3]-rb[0], rh=rb[4]-rb[1], zs=rb[5]-rb[2],
                    sdelta=max(sl)-min(sl), odelta=max(ol)-min(ol), tdelta=max(tl)-min(tl),
                    kh=len(data['keepout_hits'])
                )
                add_text(sketch, report, (rb[0], rb[4] + 12, 0), 2.0)

            try:
                app.activeViewport.fit()
            except Exception:
                pass
        except Exception:
            ui.messageBox('Failed in chip-tree v42.1 depth control:\n{}'.format(traceback.format_exc()))


def run(context):
    global app, ui
    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        ui.messageBox('RUNNING chip-tree v42.1: depth-controlled Z stacks; straight bodies ON; internal joint spheres')
    except Exception:
        pass
    try:
        old = ui.commandDefinitions.itemById(CMD_ID)
        if old:
            try:
                old.deleteMe()
            except Exception:
                pass
        cmd_def = ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_DESC)
        on_created = CommandCreatedHandler()
        cmd_def.commandCreated.add(on_created)
        handlers.append(on_created)
        cmd_def.execute()
        adsk.autoTerminate(False)
    except Exception:
        if ui:
            ui.messageBox('run failed in v42:\n{}'.format(traceback.format_exc()))


def stop(context):
    global app, ui
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        cmd_def = ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()
    except Exception:
        pass
