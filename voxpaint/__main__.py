import pyglet
import pyximport
pyximport.install(language_level=3)  # Setup cython to autocompile pyx modules

from .window import VoxpaintWindow


class OldpaintEventLoop(pyglet.app.EventLoop):

    "A tweaked event loop that lowers the idle refresh rate for less CPU heating."

    def idle(self):
        super().idle()
        return 0.05

    
if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("orafile", nargs="?")

    args = parser.parse_args()
    
    gl_config = pyglet.gl.Config(major_version=4, minor_version=5,  # Minimum OpenGL requirement
                                 double_buffer=False)  # Double buffering gives noticable cursor lag

    VoxpaintWindow(config=gl_config, path=args.orafile)
    pyglet.app.event_loop = OldpaintEventLoop()
    pyglet.app.run(0.02)
