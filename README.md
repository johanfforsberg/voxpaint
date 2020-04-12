This is a palette based drawing program in the style of Deluxe Paint, but with some more modern features such as multiple undo, "layers", etc.

The drawing is implemented as a 3D pixel array, which means that it can be "flipped" in steps of 90 degrees in any way. This is useful for drawing "voxel" type 3D images. There's a small plugin available for visualizing the result of this.

It's currently under development and not yet recommended for serious use.


#### Installation ####

Since this program is under heavy development, there's currently no way to install it without building it yourself. This process is currently only tested on my machine, under Ubuntu. There are a few dependencies, and there's is an extra step where Pyglet needs to be patched to support the latest OpenGL stuff.

A Makefile in the project dir takes care of the build procedure. Using it obviously requires GNU make, but if you don't have that it should be easy to figure out the manual steps by reading it. Dependencies are installed in a virtual environment contained in the project dir, so there's no need for administrator access. To uninstall, simply remove the "env" directory.

In the best case, you have everything needed, including python 3.7 or later, compilers etc. Then it should just be a matter of typing (from inside the git repo):

    $ make build
    $ make run
    
It will take a few seconds to start up the first time, since it uses cython to compile some parts to machine code. After that a window should appear and you're done.

If any step fails, you're probably missing some required stuff. On Ubuntu, something like the following should help.
    
    $ apt install build-essential python3-dev
    
If you get OpenGL related errors, it's possible that your hardware or driver does not support GL version 4.5. In that case you're currently out of luck.

In any case, if you try it, especially on a non-linux platform, I'd love to hear about it!


#### Usage ####

Interface is subject to change!

Mouse controls (partly depend on current tool)

- Left mouse button: draw with "foreground" color.
- Right mouse button: draw with "background" color
- Middle mouse button: pan the picture
- Scroll wheel: zoom in/out
- Shift + left click: Swith to top layer under mouse cursor
- Control + click: Take color from the pixel under mouse cursor
- Shift + scroll: Change current layer

Keyboard controls:

- arrow keys: rotate view
- w/s: change layer
- Shift + scroll: change layer
- W/S: move layer up/down
- Tools: p pencil, l line, r rectangle, f floodfill, b brush 
- o: hide all other layers
- z undo, y redo

