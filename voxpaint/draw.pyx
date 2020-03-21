"""
Implementations of primitive drawing operations on numpy arrays.
"""

cimport cython

from libc.stdlib cimport abs as iabs

from .rect cimport Rectangle


@cython.boundscheck(False)  # Deactivate bounds checking
@cython.wraparound(False)   # Deactivate negative indexing.
cpdef void paste(unsigned int [:, :] pic, unsigned int [:, :] brush, int x, int y) nogil:
    "Copy image data without caring about transparency"
    cdef int w, h, bw, bh
    w, h = pic.shape[:2]
    bw, bh = brush.shape[:2]

    cdef int px0, px1, py0, py1, bx0, bx1, by0, by1
    px0 = max(0, x)
    px1 = min(w, x + bw)
    py0 = max(0, y)
    py1 = min(h, y + bh)
    if (px0 < px1) and (py0 < py1):
        bx0 = px0 - x
        bx1 = px1 - x
        by0 = py0 - y
        by1 = py1 - y
        pic[px0:px1, py0:py1] = brush[bx0:bx1, by0:by1]


@cython.boundscheck(False)  # Deactivate bounds checking
@cython.wraparound(False)   # Deactivate negative indexing.        
cpdef Rectangle blit(unsigned int[:, :] pic, unsigned int[:, :] brush, int x, int y):
    "Draw a brush onto an image, skipping transparent pixels."
    cdef int w, h, bw, bh, y1, x1, x2, y2, xmin, ymin, xmax, ymax
    w, h = pic.shape[:2]
    bw, bh = brush.shape[:2]
    xmin = w
    ymin = h
    xmax = 0
    ymax = 0
    with nogil:
        for y1 in range(bh):
            y2 = y + y1
            if (y2 < 0):
                continue
            if (y2 >= h):
                break
            for x1 in range(bw):
                x2 = x + x1
                if (x2 < 0):
                    continue
                if (x2 >= w):
                    break
                if brush[x1, y1] >> 24:  # Ignore 100% transparent pixels
                    pic[x2, y2] = brush[x1, y1]
                    # TODO I think this can be done in a smarter way.
                    xmin = min(xmin, x2)
                    xmax = max(xmax, x2)
                    ymin = min(ymin, y2)
                    ymax = max(ymax, y2)
    return Rectangle((xmin, ymin), (xmax - xmin + 1, ymax - ymin + 1))


@cython.boundscheck(False)  # Deactivate bounds checking
@cython.wraparound(False)   # Deactivate negative indexing.        
cdef void cblit(unsigned int[:, :] pic, unsigned int[:, :] brush, int x, int y) nogil:
    "Draw a brush onto an image, skipping transparent pixels."
    # Faster version for internal use in this module.
    cdef int w, h, bw, bh, y1, x1, x2, y2
    w, h = pic.shape[:2]
    bw, bh = brush.shape[:2]
    for y1 in range(bh):
        y2 = y + y1
        if (y2 < 0):
            continue
        if (y2 >= h):
            break
        for x1 in range(bw):
            x2 = x + x1
            if (x2 < 0):
                continue
            if (x2 >= w):
                break
            if brush[x1, y1] >> 24:  # Ignore 100% transparent pixels
                pic[x2, y2] = brush[x1, y1]


@cython.boundscheck(False)  # Deactivate bounds checking
@cython.wraparound(False)   # Deactivate negative indexing.
cpdef draw_line(unsigned int [:, :] pic, unsigned int [:, :] brush,
                (int, int) p0, (int, int) p1, int step=1):

    "Draw a straight line from p0 to p1 using a brush or a single pixel of given color."

    cdef int x, y, w, h, x0, y0, x1, y1, dx, sx, dy, sy, err, bw, bh
    x, y = p0
    x0, y0 = p0
    x1, y1 = p1
    dx = iabs(x1 - x)
    sx = 1 if x < x1 else -1
    dy = -iabs(y1 - y)
    sy = 1 if y < y1 else -1
    err = dx+dy
    bw = brush.shape[0] if brush is not None else 1
    bh = brush.shape[1] if brush is not None else 1
    w, h = pic.shape[:2]

    cdef int i = 0
    cdef int e2

    cdef int px0, px1, py0, py1, bx0, bx1, by0, by1
    cdef unsigned int[:, :] src, dst
    cdef Rectangle r

    with nogil:
        while True:
            if i % step == 0:
                cblit(pic, brush, x, y)
            if x == x1 and y == y1:
                break
            e2 = 2*err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy

    cdef int x00 = max(0, min(x0, x1))
    cdef int y00 = max(0, min(y0, y1))
    cdef int x11 = min(w, max(x0, x1) + bw)
    cdef int y11 = min(h, max(y0, y1) + bh)

    return Rectangle((x00, y00), (x11 - x00, y11 - y00))


@cython.boundscheck(False)  # Deactivate bounds checking
@cython.wraparound(False)   # Deactivate negative indexing.        
cpdef draw_rectangle(unsigned int [:, :] pic, unsigned int [:, :] brush,
                     (int, int) pos, (int, int) size,
                     unsigned int color, bint fill=False):
    cdef int x0, y0, w0, h0, x, y, w, h, cols, rows, bw, bh
    x0, y0 = pos
    w0, h0 = size

    # ensure that the rectangle stays within the image borders
    x = max(0, x0)
    y = max(0, y0)
    w = w0 - (x - x0)
    h = h0 - (y - y0)

    cols, rows = pic.shape[:2]
    w = min(cols - x, w)
    h = min(rows - y, h)

    if fill:
        pic[x:x+w, y:y+h] = color
    else:
        draw_line(pic, brush, pos, (x0+w0, y0))
        draw_line(pic, brush, (x0+w0, y0), (x0+w0, y0+h0))
        draw_line(pic, brush, (x0+w0, y0+h0), (x0, y0+h0))
        draw_line(pic, brush, (x0, y0+h0), pos)   

    bw, bh = brush.shape[:2]

    cdef Rectangle pic_rect = Rectangle((0, 0), (cols, rows))
    return pic_rect.intersect(Rectangle((x, y), (min(cols, w + bw), min(rows, h + bh))))


@cython.boundscheck(False)  # Deactivate bounds checking
@cython.wraparound(False)   # Deactivate negative indexing.        
cpdef draw_fill(unsigned int [:, :] pic, (int, int) point, unsigned int color):

    # TODO kind of slow, and requires the GIL.

    cdef int startx, starty, w, h
    startx, starty = point
    cdef list stack = [point]  # TODO maybe find some more C friendly way of keeping a stack
    w, h = pic.shape[:2]
    cdef unsigned int start_col = pic[startx, starty] & 0xFF

    if start_col == color & 0xFF:
        return

    cdef int x, y, xmin, xmax, ymin, ymax, xstart
    cdef bint reach_top, reach_bottom
    xmin, xmax = w, 0
    ymin, ymax = h, 0

    while stack:
        x, y = stack.pop()
        # search left
        while x >= 0 and start_col == pic[x, y]:
            x -= 1
        x += 1
        reach_top = reach_bottom = False

        # search right
        while x < w and pic[x, y] == start_col:
            pic[x, y] = color  # color this pixel
            xmin, xmax = min(xmin, x), max(xmax, x)
            ymin, ymax = min(ymin, y), max(ymax, y)
            if 0 < y < h - 1:

                # check pixel above
                if start_col == pic[x, y-1]:
                    if not reach_top:
                        stack.append((x, y-1))  # add previous line
                        reach_top = True
                elif reach_top:
                    reach_top = False

                # check pixel below
                if start_col == pic[x, y+1]:
                    if not reach_bottom:
                        stack.append((x, y+1))  # add next line
                        reach_bottom = True
                elif reach_bottom:
                    reach_bottom = False
            x += 1

    return Rectangle((xmin, ymin), (xmax-xmin+1, ymax-ymin+1))
