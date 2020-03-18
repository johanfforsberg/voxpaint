from functools import lru_cache
import logging
from math import floor, ceil
import os
import sys

import imgui
import pyglet
from pyglet.window import key

from .drawing import Drawing
from .util import show_save_dialog, throttle


@lru_cache(256)
def as_float(color):
    r, g, b, a = color
    return (r/256, g/256, b/256, a/256)


SELECTABLE_FRAME_COLORS = [
    (0, 0, 0),         # normal
    (1, 1, 1),         # foreground
    (0.5, 0.5, 0.5),   # background
    (1, 1, 0)          # both
]


palette_overlay = {}

color_editor_open = False
current_color_page = 0


def render_palette_popup(drawing: Drawing):

    global edit_color
    global color_editor_open

    palette = drawing.palette
    fg = palette.foreground
    bg = palette.background
    fg_color = palette.foreground_color
    bg_color = palette.background_color
    open_color_editor = False

    _, opened = imgui.begin("Color popup", True)

    imgui.begin_child("Colors")

    imgui.push_style_var(imgui.STYLE_ITEM_SPACING, (0, 0))  # Make layout tighter
    width = int(imgui.get_window_content_region_width()) // 25

    for i, color in enumerate(palette.colors, 0):
        is_foreground = i == fg
        is_background = (i == bg) * 2
        selection = is_foreground | is_background
        if i in palette.overlay:
            color = as_float(palette.overlay[i])
        else:
            color = as_float(color)
        imgui.push_style_color(imgui.COLOR_FRAME_BACKGROUND,
                               *SELECTABLE_FRAME_COLORS[selection])
        if imgui.color_button(f"color {i}", *color[:3], 1, 0, 25, 25):
            # io = imgui.get_io()
            # if io.key_shift:
            #     if "spread_start" in temp_vars:
            #         temp_vars["spread_end"] = i
            #     else:
            #         temp_vars["spread_start"] = i
            # else:
            fg = i
        imgui.pop_style_color(1)

        if imgui.core.is_item_clicked(1):
            edit_color = i
            color_editor_open = True
            imgui.open_popup("Edit foreground color")
            # imgui.set_next_window_position(w - 115 - 120, 200)

        if imgui.core.is_item_clicked(2):
            # Detect right button clicks on the button
            bg = i

        if imgui.begin_drag_drop_source():
            imgui.set_drag_drop_payload('start_index', i.to_bytes(1, sys.byteorder))
            imgui.color_button(f"color {i}", *color[:3], 1, 0, 20, 20)
            imgui.end_drag_drop_source()
        if imgui.begin_drag_drop_target():
            start_index = imgui.accept_drag_drop_payload('start_index')
            if start_index is not None:
                start_index = int.from_bytes(start_index, sys.byteorder)
                io = imgui.get_io()
                image_only = io.key_shift
                # drawing.swap_colors(start_index, i, image_only=image_only)
                # palette.clear_overlay()
            imgui.end_drag_drop_target()

        # if imgui.is_item_hovered():
        #     io = imgui.get_io()
        #     delta = int(io.mouse_wheel)

        if i % width != width - 1:
            imgui.same_line()

    imgui.pop_style_var(1)
    #color_editor_open = render_color_editor_popup(drawing, edit_color, color_editor_open)

    imgui.end_child()
    imgui.end()

    palette.foreground = fg
    palette.background = bg

    return opened, open_color_editor


def render_layers(view):
    imgui.begin("Layers")

    layers = list(view.layers)
    n_layers = len(layers)
    index = view.layer_index
    x, y, z = view.direction
    # imgui.text(f"{x}, {y}, {z}")
    min_value = 0
    max_value = n_layers - 1
    if sum(view.direction) > 0:
        changed, new_index = imgui.v_slider_int("##layer_index", 30, 200, index,
                                                min_value=min_value,
                                                max_value=max_value)
    else:
        index = n_layers - index - 1
        changed, new_index = imgui.v_slider_int("##layer_index", 30, 200, index,
                                                min_value=max_value,
                                                max_value=min_value)
        index = n_layers + index + 1
    if changed:
        delta = new_index - index
        view.move_cursor(dx=x*delta, dy=y*delta, dz=z*delta)
    
    imgui.end()


def render_menu(window):

    if imgui.begin_main_menu_bar():
        
        if imgui.begin_menu("File"):

            clicked_load, selected_load = imgui.menu_item("Load", "o", False, True)
            if clicked_load:
                window.load_drawing()

            if imgui.begin_menu("Load recent...", window.recent_files):
                for path in reversed(window.recent_files):
                    clicked, _ = imgui.menu_item(os.path.basename(path), None, False, True)
                    if clicked:
                        window.load_drawing(path)
                imgui.end_menu()

            imgui.separator()
            
            clicked_save, selected_save = imgui.menu_item("Save", "Ctrl+s", False, window.drawing)
            if clicked_save:
                window.save_drawing()

            clicked_save_as, selected_save = imgui.menu_item("Save as", None, False, window.drawing)
            if clicked_save_as:
                window.save_drawing(ask_for_path=True)               
                
            imgui.end_menu()

        if imgui.begin_menu("Drawing"):
            for drawing in window.drawings:
                clicked, _ = imgui.menu_item(drawing.filename, "", False, True)
                if clicked:
                    window.drawings.select(drawing)
            imgui.end_menu()
        
        if imgui.begin_menu("Layer", window.drawing):
            ...
            imgui.end_menu()

        if imgui.begin_menu("Brush", window.drawing):
            ...
            imgui.end_menu()

        if imgui.begin_menu("Plugins", window.drawing):
            active_plugins = window.drawing.plugins.values()
            for name, plugin in window.plugins.items():
                is_active = plugin in active_plugins
                clicked, selected = imgui.menu_item(name, None, is_active, True)
                if selected:
                    window.drawing.plugins[name] = plugin
                elif is_active:
                    del window.drawing.plugins[name]
            imgui.end_menu()

        w, h = window.get_size()
        imgui.set_cursor_screen_pos((w // 2, 0))
        drawing = window.drawing
        if drawing:
            imgui.text(f"{drawing.filename} {drawing.size}")

            imgui.set_cursor_screen_pos((w - 270, 0))
            imgui.text(f"Zoom: x{2**window.zoom}")
            
            if window.mouse_position:
                imgui.set_cursor_screen_pos((w - 150, 0))
                x, y = window._to_image_coords(*window.mouse_position)
                imgui.text(f"{int(x): >3},{int(y): >3},{window.view.layer_index: >3}")

        imgui.end_main_menu_bar()                
