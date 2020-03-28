from functools import lru_cache
from inspect import isclass
import logging
from math import floor, ceil
import os
import sys

import imgui
import pyglet
from pyglet.window import key

from .drawing import Drawing
from .util import show_save_dialog, throttle


TOOL_BUTTON_COLORS = [
    (0.5, 0.5, 0.5),  # normal
    (1, 1, 1)         # selected
]

SELECTABLE_FRAME_COLORS = [
    (0, 0, 0),         # normal
    (1, 1, 1),         # foreground
    (0.5, 0.5, 0.5),   # background
    (1, 1, 0)          # both
]


palette_overlay = {}

color_editor_open = False
current_color_page = 0


@lru_cache(256)
def as_float(color):
    r, g, b, a = color
    return (r/256, g/256, b/256, a/256)


@lru_cache(256)
def as_int(color):
    r, g, b, a = color
    return (int(r * 256), int(g * 256), int(b * 256), int(a * 256))


def _change_channel(value, delta):
    return max(0, min(255, value + delta))


def render_tools(tools, icons):
    current_tool = tools.current
    selected = False
    for i, tool in enumerate(tools):
        texture = icons[tool.tool.name]
        with imgui.colored(imgui.COLOR_BUTTON, *TOOL_BUTTON_COLORS[tool == current_tool]):
            if imgui.image_button(texture.name, 16, 16):
                tools.select(tool.tool)
                selected = True
            if i % 3 != 2 and not i == len(tools) - 1:
                imgui.same_line()
        if imgui.is_item_hovered():
            imgui.begin_tooltip()
            imgui.text(tool.tool.name.lower())
            imgui.end_tooltip()
    return selected


def render_color_editor(orig, color):
    r, g, b, a = color

    io = imgui.get_io()

    delta = 0
    imgui.push_id("R")
    # TODO find a less verbose way to do something like this:
    # imgui.push_style_color(imgui.COLOR_FRAME_BACKGROUND, r/255, 0, 0)
    # imgui.push_style_color(imgui.COLOR_FRAME_BACKGROUND_HOVERED, r/255, 0, 0)
    # imgui.push_style_color(imgui.COLOR_FRAME_BACKGROUND_ACTIVE, r/255, 0, 0)
    # imgui.push_style_color(imgui.COLOR_SLIDER_GRAB, 1, 1, 1)
    # imgui.push_style_color(imgui.COLOR_SLIDER_GRAB_ACTIVE, 1, 1, 1)
    _, r = imgui.v_slider_int("", 30, 255, r, min_value=0, max_value=255)
    # imgui.pop_style_color()
    # imgui.pop_style_color()
    # imgui.pop_style_color()
    # imgui.pop_style_color()
    # imgui.pop_style_color()
    if imgui.is_item_hovered():
        delta = int(io.mouse_wheel)
        if not io.key_shift:
            r = _change_channel(r, delta)
    imgui.pop_id()
    imgui.same_line()
    imgui.push_id("G")
    _, g = imgui.v_slider_int("", 30, 255, g, min_value=0, max_value=255)
    if imgui.is_item_hovered():
        delta = int(io.mouse_wheel)
        if not io.key_shift:
            g = _change_channel(g, delta)
    imgui.pop_id()
    imgui.same_line()
    imgui.push_id("B")
    _, b = imgui.v_slider_int("", 30, 255, b, min_value=0, max_value=255)
    if imgui.is_item_hovered():
        delta = int(io.mouse_wheel)
        if not io.key_shift:
            b = _change_channel(b, delta)
    imgui.pop_id()

    if delta and io.key_shift:
        r = _change_channel(r, delta)
        g = _change_channel(g, delta)
        b = _change_channel(b, delta)

    if imgui.checkbox("Transp.", a == 0)[1]:
        a = 0
    else:
        a = 255

    imgui.color_button("Current color", *as_float(orig))
    imgui.same_line()
    imgui.text("->")
    imgui.same_line()
    imgui.color_button("Current color", *as_float(color))

    if imgui.button("OK"):
        imgui.close_current_popup()
        return True, False, (r, g, b, a)
    imgui.same_line()
    if imgui.button("Cancel"):
        imgui.close_current_popup()
        return False, True, (r, g, b, a)
    return False, False, (r, g, b, a)


palette_overlay = {}

color_editor_open = False
current_color_page = 0


def render_palette(drawing: Drawing):

    global color_editor_open  # Need a persistent way to keep track of the popup being closed...
    global current_color_page

    palette = drawing.palette
    fg = palette.foreground
    bg = palette.background
    fg_color = palette.foreground_color
    bg_color = palette.background_color

    imgui.begin_child("Palette", border=False, height=460)
    # Edit foreground color
    if imgui.color_button(f"Foreground (#{fg})", *as_float(fg_color), 0, 30, 30):
        io = imgui.get_io()
        w, h = io.display_size
        imgui.open_popup("Edit foreground color")
        imgui.set_next_window_position(w - 115 - 120, 200)
        color_editor_open = True
    if imgui.begin_popup("Edit foreground color", flags=(imgui.WINDOW_NO_MOVE |
                                                         imgui.WINDOW_NO_SCROLL_WITH_MOUSE)):
        done, cancelled, new_color = render_color_editor(palette.colors[fg], fg_color)
        if done and new_color != fg_color:
            drawing.change_colors(fg, new_color)
            palette.clear_overlay()
        elif cancelled:
            palette.clear_overlay()
        else:
            palette.set_overlay(fg, new_color)
        imgui.end_popup()
    elif color_editor_open:
        # The popup was closed by clicking outside, keeping the change (same as OK)
        drawing.change_colors(fg, fg_color)
        palette.clear_overlay()
        color_editor_open = False

    imgui.same_line()

    imgui.color_button(f"Background (#{bg})", *as_float(bg_color), 0, 30, 30)
    
    max_pages = len(palette.colors) // 64 - 1
    imgui.push_item_width(100)
    _, current_color_page = imgui.slider_int("Page", current_color_page, min_value=0, max_value=max_pages)
    start_color = 64 * current_color_page

    imgui.begin_child("Colors", border=False)
    imgui.push_style_var(imgui.STYLE_ITEM_SPACING, (0, 0))  # Make layout tighter
    width = int(imgui.get_window_content_region_width()) // 20

    imgui.push_style_color(imgui.COLOR_FRAME_BACKGROUND, 0, 0, 0)
    
    for i, color in enumerate(palette.colors[start_color:start_color + 64], start_color):
        is_foreground = i == fg
        is_background = (i == bg) * 2
        selection = is_foreground | is_background
        color = as_float(color)

        if color[3] == 0 or selection:
            x, y = imgui.get_cursor_screen_pos()
        
        if imgui.color_button(f"color {i}", *color[:3], 1, 0, 25, 25):
            # io = imgui.get_io()
            # if io.key_shift:
            #     if "spread_start" in temp_vars:
            #         temp_vars["spread_end"] = i
            #     else:
            #         temp_vars["spread_start"] = i
            # else:
            fg = i

        if i % width != width - 1:
            imgui.same_line()

        draw_list = imgui.get_window_draw_list()            
        if color[3] == 0:
            # Mark transparent color
            draw_list.add_line(x+1, y+1, x+24, y+24, imgui.get_color_u32_rgba(0, 0, 0, 1), 1)
            draw_list.add_line(x+1, y+2, x+23, y+24, imgui.get_color_u32_rgba(1, 1, 1, 1), 1)
            
        if is_foreground:
            # Mark foregroupd color
            draw_list.add_rect_filled(x+2, y+2, x+10, y+10, imgui.get_color_u32_rgba(1, 1, 1, 1))
            draw_list.add_rect(x+2, y+2, x+10, y+10, imgui.get_color_u32_rgba(0, 0, 0, 1))
        if is_background:
            # Mark background color
            draw_list.add_rect_filled(x+15, y+2, x+23, y+10, imgui.get_color_u32_rgba(0, 0, 0, 1))
            draw_list.add_rect(x+15, y+2, x+23, y+10, imgui.get_color_u32_rgba(1, 1, 1, 1))

        if imgui.core.is_item_clicked(2):
            # Right button sets background
            bg = i

        # Drag and drop (currently does not accomplish anything though)
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
                drawing.swap_colors(start_index, i, image_only=image_only)
                palette.clear_overlay()
            imgui.end_drag_drop_target()

    imgui.pop_style_color(1)
    imgui.pop_style_var(1)
    imgui.end_child()
    
    imgui.end_child()

    if imgui.is_item_hovered():
        io = imgui.get_io()
        delta = int(io.mouse_wheel)
        current_color_page = min(max(current_color_page - delta, 0), max_pages)

    palette.foreground = fg
    palette.background = bg

    # if "spread_start" in temp_vars and "spread_end" in temp_vars:
    #     spread_start = temp_vars.pop("spread_start")
    #     spread_end = temp_vars.pop("spread_end")
    #     from_index = min(spread_start, spread_end)
    #     to_index = max(spread_start, spread_end)
    #     spread_colors = palette.spread(from_index, to_index)
    #     drawing.change_colors(from_index + 1, spread_colors)


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

    imgui.begin_child("Colors", height=0)

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

    "Layer selector. Currently extremely spare."

    layers = list(view.layers)
    n_layers = len(layers)
    index = view.layer_index
    changed, new_index = imgui.v_slider_int("##layer_index", 30, 100, index,
                                            min_value=0, max_value=n_layers - 1)
    if changed:
        x, y, z = view.direction
        delta = new_index - index
        view.move_cursor(dx=x*delta, dy=y*delta, dz=z*delta)
        

def render_menu(window):

    "Main menu bar."

    if imgui.begin_main_menu_bar():
        
        if imgui.begin_menu("File"):

            clicked_load, selected_load = imgui.menu_item("Load", "", False, True)
            if clicked_load:
                window.load_drawing()

            if imgui.begin_menu("Load recent...", window.recent_files):
                for path in reversed(list(window.recent_files)):
                    clicked, _ = imgui.menu_item(os.path.basename(path), None, False, True)
                    if clicked:
                        window.load_drawing(path)
                imgui.end_menu()

            imgui.separator()
            
            clicked_save, selected_save = imgui.menu_item("Save", "", False, window.drawing)
            if clicked_save:
                window.save_drawing()

            clicked_save_as, selected_save = imgui.menu_item("Save as", None, False, window.drawing)
            if clicked_save_as:
                window.save_drawing(ask_for_path=True)               
                
            imgui.end_menu()

        if imgui.begin_menu("Drawing"):

            if imgui.menu_item("New", "", False, True)[0]:
                window.create_drawing()

            if imgui.menu_item("Close", "", False, window.drawing)[0]:
                window.close_drawing()
                
            if window.drawings:
                imgui.separator()

                for drawing in window.drawings:
                    selected = drawing == window.drawing
                    clicked, _ = imgui.menu_item(drawing.filename, "", selected, True)
                    if clicked:
                        window.drawings.select(drawing)
            imgui.end_menu()

        if imgui.begin_menu("View", window.view):
            
            clicked, active = imgui.menu_item("Only show current layer", "",
                                              window.view.show_only_current_layer, True)
            if clicked:
                window.view.show_only_current_layer = active

            imgui.separator()
            
            if imgui.menu_item("Rotate up", "UP", False, True)[0]:
                window.view.rotate(dx=-1)
            if imgui.menu_item("Rotate down", "DOWN", False, True)[0]:
                window.view.rotate(dx=1)
            if imgui.menu_item("Rotate left", "LEFT", False, True)[0]:
                window.view.rotate(dz=-1)
            if imgui.menu_item("Rotate right", "RIGHT", False, True)[0]:
                window.view.rotate(dz=1)

            if imgui.menu_item("Reset rotation", "", False, True)[0]:
                window.view.rotation = (0, 0, 0)
                
            imgui.end_menu()
            
        if imgui.begin_menu("Layer", window.drawing):

            if imgui.menu_item("Next layer", "w", False, window.view.layer_index < window.view.depth - 1)[0]:
                window.view.next_layer()

            if imgui.menu_item("Previous layer", "s", False, window.view.layer_index > 0)[0]:
                window.view.prev_layer()

            imgui.separator()
            
            if imgui.menu_item("Move layer up", "W", False, window.view.layer_index < window.view.depth - 1)[0]:
                window.view.move_layer(+1)

            if imgui.menu_item("Move layer down", "S", False, window.view.layer_index > 0)[0]:
                window.view.move_layer(-1)

            imgui.separator()

            if imgui.menu_item("Visibility", "V", window.view.layer_visible, True)[0]:
                window.view.toggle_layer()
                
            imgui.end_menu()

        if imgui.begin_menu("Brush", window.drawing):
            drawing = window.drawing
            for brush in drawing.brushes[-10:]:
                clicked, active = imgui.menu_item(f"{brush.size}", "", brush == drawing.brush, True)
                if clicked:
                    if brush == drawing.brush:
                        drawing.brushes.select(None)
                    else:
                        drawing.brushes.select(brush)
            imgui.end_menu()

        if imgui.begin_menu("Plugins", window.drawing):
            active_plugins = window.drawing.plugins.values()
            for name, plugin in window.plugins.items():
                is_active = plugin in active_plugins
                clicked, selected = imgui.menu_item(name, None, is_active, True)
                if selected:
                    (plugin, sig, args) = plugin
                    if isclass(plugin):
                        window.drawing.plugins[name] = plugin(), sig, args
                    else:
                        window.drawing.plugins[name] = plugin, sig, args
                elif is_active:
                    del window.drawing.plugins[name]
            imgui.end_menu()

        w, h = window.get_size()
        imgui.set_cursor_screen_pos((w // 2, 0))
        drawing = window.drawing
        if drawing:
            imgui.text(f"{drawing.filename} {drawing.size}")

            imgui.set_cursor_screen_pos((w - 370, 0))
            imgui.text(f"Zoom: {2**window.zoom}x  Rot: {window.view.rotation}")
            
            if window.mouse_position:
                imgui.set_cursor_screen_pos((w - 150, 0))
                x, y = window._to_image_coords(*window.mouse_position)
                imgui.text(f"{int(x): >3},{int(y): >3},{window.view.layer_index: >3}")

        imgui.end_main_menu_bar()                

        
def render_new_drawing_popup(window):

    "Settings for creating a new drawing."

    if window._new_drawing:
        imgui.open_popup("New drawing")
        w, h = window.get_size()
        imgui.set_next_window_size(200, 120)
        imgui.set_next_window_position(w // 2 - 100, h // 2 - 60)

    if imgui.begin_popup_modal("New drawing")[0]:
        imgui.text("Creating a new drawing.")
        imgui.separator()
        changed, new_size = imgui.drag_int3("Shape", *window._new_drawing["shape"],
                                            min_value=1, max_value=2048)
        if changed:
            window._new_drawing["shape"] = new_size
        if imgui.button("OK"):
            window.really_create_drawing()
            imgui.close_current_popup()
        imgui.same_line()
        if imgui.button("Cancel"):
            window._new_drawing = None
            imgui.close_current_popup()
        imgui.end_popup()

        
def render_errors(window):
    
    if window._error:
        imgui.open_popup("Error")
        if imgui.begin_popup_modal("Error")[0]:
            imgui.text(window._error)
            if imgui.button("Doh!"):
                window._error = None
                imgui.close_current_popup()
            imgui.end_popup()
    

def render_unsaved_close_drawing(window):

    "Popup to prevent accidentally closing a drawing with unsaved work."
    
    drawing = window.close_unsaved_drawing
    
    if drawing and drawing.unsaved:
        imgui.open_popup("Really close?")

    if imgui.begin_popup_modal("Really close?", flags=imgui.WINDOW_NO_RESIZE)[0]:
        imgui.text("The drawing contains unsaved work.")
        if imgui.button("Yes, close anyway"):
            window.drawings.remove(drawing)
            window.close_unsaved_drawing = None
            imgui.close_current_popup()        
        imgui.same_line()
        if imgui.button("Yes, but save first"):
            window.save_drawing(drawing)
            window.drawings.remove(drawing)
            window.close_unsaved_drawing = None
            imgui.close_current_popup()
        imgui.same_line()
        if imgui.button("No, cancel"):
            window.close_unsaved_drawing = None
            imgui.close_current_popup()
        imgui.end_popup()
            

def render_unsaved_exit(window):

    "Popup to prevent exiting the application with unsaved work."
    
    if window.exit_unsaved_drawings:
        imgui.open_popup("Really exit?")

    imgui.set_next_window_size(500, 200)
    if imgui.begin_popup_modal("Really exit?")[0]:
        imgui.text("You have unsaved work in these drawing(s):")

        imgui.begin_child("unsaved", border=True,
                          height=imgui.get_content_region_available()[1] - 26)
        for drawing in window.exit_unsaved_drawings:
            imgui.text(drawing.filename)
            if imgui.is_item_hovered():
                pass  # TODO popup thumbnail of the picture?
        imgui.end_child()

        if imgui.button("Yes, exit anyway"):
            imgui.close_current_popup()
            pyglet.app.exit()
        imgui.same_line()
        if imgui.button("Yes, but save first"):
            for drawing in window.exit_unsaved_drawings:
                window.save_drawing(drawing)
            pyglet.app.exit()
        imgui.same_line()
        if imgui.button("No, cancel"):
            window.exit_unsaved_drawings = None
            imgui.close_current_popup()
        imgui.end_popup()
            
        
