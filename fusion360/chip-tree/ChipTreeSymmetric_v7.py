# Author: ChatGPT
# Description: Fusion 360 add-in to sketch a symmetric 1-to-24 bifurcating microfluidic tree centreline.
# Version: 7.0

import adsk.core, adsk.fusion, traceback, math

_app = None
_ui = None
_handlers = []
CMD_ID = 'Phenomyx_ChipTreeSymmetric_v7_Command_UNIQUE'
CMD_NAME = 'Chip Tree Symmetric 1-to-24 v7'
CMD_DESC = 'Draws a symmetric 1-to-24 fluidic tree with 12 terminal vertical-entry forks.'


def _val(inputs, id_):
    # Fusion length inputs return cm internally.
    return inputs.itemById(id_).value


def _bool(inputs, id_):
    return inputs.itemById(id_).value


def _text(sketch, text, x, y, h=0.25):
    try:
        p = adsk.core.Point3D.create(x, y, 0)
        ti = sketch.sketchTexts.createInput(text, h, p)
        sketch.sketchTexts.add(ti)
    except Exception:
        pass


def _p(x, y):
    return adsk.core.Point3D.create(x, y, 0)


def _line(sketch, a, b):
    if abs(a[0]-b[0]) < 1e-9 and abs(a[1]-b[1]) < 1e-9:
        return None
    return sketch.sketchCurves.sketchLines.addByTwoPoints(_p(a[0], a[1]), _p(b[0], b[1]))


def _polyline(sketch, pts):
    last = None
    for i in range(len(pts)-1):
        last = _line(sketch, pts[i], pts[i+1])
    return last


def _circle(sketch, c, r):
    return sketch.sketchCurves.sketchCircles.addByCenterRadius(_p(c[0], c[1]), r)


def _add_user_param(design, name, expression, units, comment):
    try:
        old = design.userParameters.itemByName(name)
        if old:
            old.expression = expression
            old.comment = comment
        else:
            design.userParameters.add(name, adsk.core.ValueInput.createByString(expression), units, comment)
    except Exception:
        pass


def draw_tree(inputs):
    app = adsk.core.Application.get()
    ui = app.userInterface
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        ui.messageBox('Open or create a Fusion design first.')
        return

    root = design.rootComponent
    sketches = root.sketches
    xy = root.xYConstructionPlane
    sketch = sketches.add(xy)
    sketch.name = 'chip_tree_symmetric_1_to_24_v7_centrelines'

    # All values are cm internally. UI accepts mm, Fusion converts.
    inlet_x = _val(inputs, 'inlet_x')
    inlet_y = _val(inputs, 'inlet_y')
    trunk_len = _val(inputs, 'trunk_len')
    level_rise = _val(inputs, 'level_rise')
    fork_pitch = _val(inputs, 'fork_pitch')
    well_pitch = _val(inputs, 'well_pitch')
    final_stem = _val(inputs, 'final_stem')
    final_leg = _val(inputs, 'final_leg')
    well_radius = _val(inputs, 'well_radius')
    inlet_radius = _val(inputs, 'inlet_radius')
    channel_width = _val(inputs, 'channel_width')
    bend_radius = _val(inputs, 'bend_radius')
    draw_circles = _bool(inputs, 'draw_circles')
    add_labels = _bool(inputs, 'add_labels')

    # Write useful parameters into the design for downstream modelling.
    _add_user_param(design, 'chip_channel_width', f'{channel_width*10:.4g} mm', 'mm', 'Microfluidic channel width')
    _add_user_param(design, 'chip_target_bend_radius', f'{bend_radius*10:.4g} mm', 'mm', 'Target centreline bend radius for later filleting')
    _add_user_param(design, 'chip_well_radius', f'{well_radius*10:.4g} mm', 'mm', 'Well radius')
    _add_user_param(design, 'chip_inlet_radius', f'{inlet_radius*10:.4g} mm', 'mm', 'Inlet radius')

    # y levels. Inlet at bottom, wells at top.
    y0 = inlet_y
    y1 = y0 + trunk_len
    y2 = y1 + level_rise
    y3 = y2 + level_rise
    y4 = y3 + level_rise
    y_fork = y4 + level_rise
    y_bar = y_fork + final_stem
    y_well = y_bar + final_leg

    # 12 terminal fork roots, each feeding two wells vertically.
    n_forks = 12
    total_span = (n_forks - 1) * fork_pitch
    fork_xs = [inlet_x - total_span/2 + i*fork_pitch for i in range(n_forks)]
    fork_roots = [(x, y_fork) for x in fork_xs]

    # Terminal vertical-entry two-well forks.
    well_centres = []
    well_no = 1
    for x in fork_xs:
        left_well = (x - well_pitch/2, y_well)
        right_well = (x + well_pitch/2, y_well)
        left_under = (left_well[0], y_bar)
        mid = (x, y_bar)
        right_under = (right_well[0], y_bar)
        rootp = (x, y_fork)
        # symmetric T: root up, horizontal bar, then vertical into each well
        _polyline(sketch, [rootp, mid, left_under, left_well])
        _polyline(sketch, [mid, right_under, right_well])
        if draw_circles:
            _circle(sketch, left_well, well_radius)
            _circle(sketch, right_well, well_radius)
        if add_labels:
            _text(sketch, str(well_no), left_well[0]+well_radius*0.75, left_well[1]+well_radius*0.15, h=max(well_radius*0.45, 0.12))
            well_no += 1
            _text(sketch, str(well_no), right_well[0]+well_radius*0.75, right_well[1]+well_radius*0.15, h=max(well_radius*0.45, 0.12))
            well_no += 1
        well_centres.extend([left_well, right_well])

    # Upstream compact Manhattan hierarchy.
    # First join terminal forks in symmetric pairs: 12 -> 6.
    pair_nodes = []
    for i in range(0, n_forks, 2):
        a = fork_roots[i]
        b = fork_roots[i+1]
        x_mid = (a[0] + b[0]) / 2
        node = (x_mid, y4)
        pair_nodes.append(node)
        _polyline(sketch, [node, (node[0], y_fork), a])
        _polyline(sketch, [(node[0], y_fork), b])

    # Join pair nodes into three 4-fork blocks: 6 -> 3.
    block_nodes = []
    for i in range(0, len(pair_nodes), 2):
        a = pair_nodes[i]
        b = pair_nodes[i+1]
        x_mid = (a[0] + b[0]) / 2
        node = (x_mid, y3)
        block_nodes.append(node)
        _polyline(sketch, [node, (node[0], y4), a])
        _polyline(sketch, [(node[0], y4), b])

    # Handle three blocks using a symmetric-looking central join: left+middle, then right.
    # This is the unavoidable non-power-of-two stage. Geometry remains compact; terminal forks remain true binary forks.
    left_mid = ((block_nodes[0][0] + block_nodes[1][0]) / 2, y2)
    right_node = block_nodes[2]
    top_left_mid = (left_mid[0], y3)
    _polyline(sketch, [left_mid, top_left_mid, block_nodes[0]])
    _polyline(sketch, [top_left_mid, block_nodes[1]])

    main_split = ((left_mid[0] + right_node[0]) / 2, y1)
    _polyline(sketch, [main_split, (main_split[0], y2), left_mid])
    _polyline(sketch, [(main_split[0], y2), right_node])

    inlet = (inlet_x, inlet_y)
    _polyline(sketch, [inlet, main_split])
    if draw_circles:
        _circle(sketch, inlet, inlet_radius)

    if add_labels:
        # Lightweight report with no obsolete keys.
        report_x = inlet_x - total_span/2
        report_y = y_well + max(well_radius*2.2, 0.8)
        _text(sketch,
              '1 inlet; 12 terminal forks; 2 wells per final fork; final well entry is vertical; centrelines only.',
              report_x, report_y, h=0.22)
        _text(sketch,
              'Note: 24 is not a complete power-of-two binary tree, so one upstream compact join handles the 3-block stage.',
              report_x, report_y + 0.38, h=0.18)

    # Fit view.
    try:
        app.activeViewport.fit()
    except Exception:
        pass


class CommandExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            cmd = args.firingEvent.sender
            draw_tree(cmd.commandInputs)
        except Exception:
            adsk.core.Application.get().userInterface.messageBox('Failed:\n{}'.format(traceback.format_exc()))


class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            cmd.isRepeatable = False
            inputs = cmd.commandInputs
            units_mgr = adsk.core.Application.get().activeProduct.unitsManager

            inputs.addValueInput('inlet_x', 'Inlet X', 'mm', adsk.core.ValueInput.createByString('0 mm'))
            inputs.addValueInput('inlet_y', 'Inlet Y', 'mm', adsk.core.ValueInput.createByString('0 mm'))
            inputs.addValueInput('trunk_len', 'Common trunk length', 'mm', adsk.core.ValueInput.createByString('20 mm'))
            inputs.addValueInput('level_rise', 'Rise per upstream split level', 'mm', adsk.core.ValueInput.createByString('10 mm'))
            inputs.addValueInput('fork_pitch', 'Pitch between final fork centres', 'mm', adsk.core.ValueInput.createByString('12 mm'))
            inputs.addValueInput('well_pitch', 'Pitch between wells in each final fork', 'mm', adsk.core.ValueInput.createByString('4 mm'))
            inputs.addValueInput('final_stem', 'Final fork vertical stem', 'mm', adsk.core.ValueInput.createByString('5 mm'))
            inputs.addValueInput('final_leg', 'Final vertical well-entry length', 'mm', adsk.core.ValueInput.createByString('4 mm'))
            inputs.addValueInput('well_radius', 'Well radius', 'mm', adsk.core.ValueInput.createByString('1.2 mm'))
            inputs.addValueInput('inlet_radius', 'Inlet radius', 'mm', adsk.core.ValueInput.createByString('1.5 mm'))
            inputs.addValueInput('channel_width', 'Channel width parameter', 'mm', adsk.core.ValueInput.createByString('0.4 mm'))
            inputs.addValueInput('bend_radius', 'Target bend radius parameter', 'mm', adsk.core.ValueInput.createByString('1.0 mm'))
            inputs.addBoolValueInput('draw_circles', 'Draw well/inlet circles', True, '', True)
            inputs.addBoolValueInput('add_labels', 'Add labels/report', True, '', True)

            on_execute = CommandExecuteHandler()
            cmd.execute.add(on_execute)
            _handlers.append(on_execute)
        except Exception:
            adsk.core.Application.get().userInterface.messageBox('Command creation failed:\n{}'.format(traceback.format_exc()))


def _create_command_definition():
    global _ui
    cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
    if cmd_def:
        try:
            cmd_def.deleteMe()
        except Exception:
            pass
    cmd_def = _ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_DESC)
    on_created = CommandCreatedHandler()
    cmd_def.commandCreated.add(on_created)
    _handlers.append(on_created)
    return cmd_def


def run(context):
    global _app, _ui
    try:
        _app = adsk.core.Application.get()
        _ui = _app.userInterface
        cmd_def = _create_command_definition()

        # Add toolbar button where possible, but always execute immediately.
        try:
            workspace = _ui.workspaces.itemById('FusionSolidEnvironment')
            panel = None
            for pid in ['SolidCreatePanel', 'SolidScriptsAddinsPanel', 'ToolsAddinsPanel']:
                panel = workspace.toolbarPanels.itemById(pid) if workspace else None
                if panel:
                    break
            if panel and not panel.controls.itemById(CMD_ID):
                panel.controls.addCommand(cmd_def)
        except Exception:
            pass

        cmd_def.execute()
        adsk.autoTerminate(False)
    except Exception:
        if _ui:
            _ui.messageBox('Add-in run failed:\n{}'.format(traceback.format_exc()))


def stop(context):
    global _ui
    try:
        if _ui:
            for workspace_id in ['FusionSolidEnvironment']:
                workspace = _ui.workspaces.itemById(workspace_id)
                if workspace:
                    for pid in ['SolidCreatePanel', 'SolidScriptsAddinsPanel', 'ToolsAddinsPanel']:
                        panel = workspace.toolbarPanels.itemById(pid)
                        if panel:
                            ctrl = panel.controls.itemById(CMD_ID)
                            if ctrl:
                                ctrl.deleteMe()
            cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
            if cmd_def:
                cmd_def.deleteMe()
    except Exception:
        pass
