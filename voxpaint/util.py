from functools import lru_cache, wraps
import logging
from time import time
from tkinter import Tk, filedialog
from traceback import format_exc

from euclid3 import Matrix4
import imgui
import pyglet


def try_except_log(f):
    "A decorator useful for debugging event callbacks whose exceptions get eaten."
    def inner(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception:
            logging.error(format_exc())
    return inner


class Selectable:

    """
    Wrapper for a list of items where one can be selected.
    Also supports adding and removing items.
    """

    def __init__(self, items=None):
        self.items = items or []
        self.current = items[0] if items else None

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)

    def __reversed__(self):
        return reversed(self.items)

    def __getitem__(self, index):
        return self.items[index]

    def __setitem__(self, index, item):
        self.set_item(item, index)

    def index(self, item=None):
        return self.items.index(item or self.current)

    def select(self, item):
        assert item in self.items, f"No such item {item}!"
        self.current = item

    def set_item(self, item, index=None):
        current_index = self.get_current_index()
        if index is None or index == current_index:
            self.items[current_index] = self.current = item
        else:
            self.items[index] = item

    def get_current_index(self):
        if self.current is None:
            return None
        if self.current not in self.items:
            self.current = None
            return None
        return self.items.index(self.current)

    def add(self, item, index=None):
        if self.items:
            index = index if index is not None else self.get_current_index()
            self.items.insert(index, item)
        else:
            self.items.append(item)
        self.current = item

    def append(self, item):
        self.items.append(item)
        self.current = item

    def remove(self, item=None):
        item = item or self.current
        try:
            index = self.items.index(item)
            self.items.remove(item)
            self.current = self.items[min(index, len(self.items) - 1)]
        except (ValueError, IndexError):
            self.current = None

    def cycle_forward(self, cyclic=False):
        index = self.get_current_index()
        if not cyclic and index == len(self) - 1:
            return
        index = (self.get_current_index() + 1) % len(self.items)
        self.current = self.items[index]

    def cycle_backward(self, cyclic=False):
        index = self.get_current_index()
        if not cyclic and index == 0:
            return
        index = (index - 1) % len(self.items)
        self.current = self.items[index]

    def swap(self, a, b=None):
        b = self.get_current_index() if b is None else b
        self.items[a], self.items[b] = self.items[b], self.items[a]


class Selectable2:

    def __init__(self, items: dict):
        self._items = items
        self._current_key = list(items.keys())[0]
        self._last = []

    @property
    def current(self):
        return self._items[self._current_key]

    def select(self, key):
        print(self._items)
        assert key in self._items
        try:
            self._last.remove(key)
        except ValueError:
            pass
        self._last.append(key)
        self._current_key = key        

    def __iter__(self):
        return iter(self._items.values())
    

def throttle(interval=0.1):
    """
    A decorator that ensures that the function is not run more often
    than the given interval, no matter how often it's called.
    Uses the pyglet clock to schedule calls.
    """
    scheduled_at = None

    def wrap(f):
        def inner(*args, **kwargs):
            nonlocal scheduled_at
            now = time()
            if scheduled_at and scheduled_at > now:
                return
            scheduled_at = now + interval

            pyglet.clock.schedule_once(lambda dt: f(*args, **kwargs), interval)
        return inner

    return wrap


def debounce(cooldown=60, wait=3):
    """
    A decorator that gives the function a "cooldown" period given in seconds,
    from the first call, during which calling the function has no effect.
    After the cooldown, the function will be called as soon as it has not been
    called within the last <wait> seconds. After that the cooldown is reset.
    """
    sleep_until = None

    def wrap(f):

        def do(dt, *args, **kwargs):
            nonlocal sleep_until
            sleep_until = None
            f(*args, **kwargs)

        def inner(*args, **kwargs):
            nonlocal sleep_until
            now = time()
            if not sleep_until:
                sleep_until = now + cooldown
                pyglet.clock.schedule_once(do, cooldown, *args, **kwargs)
                return
            if now < sleep_until - wait:
                return
            pyglet.clock.unschedule(do)
            pyglet.clock.schedule_once(do, wait, *args, **kwargs)

        def cancel():
            pyglet.clock.unschedule(do)

        inner.cancel = cancel
        return inner

    return wrap


class AutoResetting:

    "A descriptor that automatically restores its default value some time after being set."

    def __init__(self, default, reset_time=1):
        self.value = self.default = default
        self.reset_time = 0.5

    def __get__(self, obj, type=None):
        return self.value

    def __set__(self, obj, value):
        self.value = value
        pyglet.clock.unschedule(self._reset)
        pyglet.clock.schedule_once(self._reset, self.reset_time)
        
    def _reset(self, dt):
        self.value = self.default
    

def cache_clear(cached_func):
    """Decorator that calls cache_clear on the given lru_cached function after
    the decorated function gets called."""
    def inner(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            f(*args, **kwargs)
            cached_func.cache_clear()
        return wrapped
    return inner


@lru_cache(1)
def make_view_matrix(window_size, image_size, zoom, offset):
    "Calculate a view matrix that places the image on the screen, at scale."
    ww, wh = window_size
    iw, ih = image_size

    scale = 2**zoom
    width = ww / iw / scale
    height = wh / ih / scale
    far = 10
    near = -10

    frust = Matrix4()
    frust[:] = (2/width, 0, 0, 0,
                0, 2/height, 0, 0,
                0, 0, -2/(far-near), 0,
                0, 0, -(far+near)/(far-near), 1)

    x, y = offset
    lx = x / iw / scale
    ly = y / ih / scale

    view = (Matrix4()
            .new_translate(lx, ly, 0))

    return frust * view


@lru_cache(1)
def make_view_matrix_inverse(window_size, image_size, zoom, offset):
    return make_view_matrix(window_size, image_size, zoom, offset).inverse()


def show_load_dialog(**args):
    Tk().withdraw()  # disables TkInter GUI
    return filedialog.askopenfilename(**args)


def show_save_dialog(**args):
    Tk().withdraw()
    return filedialog.asksaveasfilename(**args)


def no_imgui_events(f):
    "Decorator for event callbacks that should ignore events on imgui windows."
    def inner(*args):
        io = imgui.get_io()
        if not (io.want_capture_mouse or io.want_capture_keyboard):
            f(*args)
    return inner
