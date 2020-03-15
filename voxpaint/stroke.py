from time import sleep

from .util import try_except_log


@try_except_log
def make_stroke(view, event_queue, tool):

    """
    This function will consume events on the given queue until it receives
    a mouse_up event. It's expected to be running in a thread.
    """

    event_type = None

    event_type, *args = event_queue.get()
    assert event_type == "mouse_down"
    tool.start(view, *args)

    while True:

        # First check for events
        if tool.period is None:
            event_type, *args = event_queue.get()
            while not event_queue.empty():
                # In case something gets slow, let's skip any accumulated events
                event_type, *args = event_queue.get()
        else:
            sleep(tool.period)
            while not event_queue.empty():
                event_type, *args = event_queue.get()

            if event_type is None:
                continue

        if event_type == "abort":
            return None

        # Now use the tool appropriately
        if event_type == "mouse_drag":
            # with layer.lock:
            # By taking the lock here we can prevent flickering.
            if tool.ephemeral and tool.rect:
                overlay.clear(tool.rect)
            tool.draw(view, *args)
        elif event_type == "mouse_up":
            print("done")
            tool.finish(view, *args)
            break

    return tool
