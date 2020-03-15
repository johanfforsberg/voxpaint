cimport cython

# from libc.math cimport abs
# from libcpp.complex cimport abs
from libc.stdlib cimport abs as iabs

# from .picture cimport LongPicture
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
cpdef void blit(unsigned int[:, :] pic, unsigned int[:, :] brush, int x, int y) nogil:
    "Draw a brush onto an image, skipping transparent pixels."
    cdef int w, h, bw, bh, y1, x1, x2, y2, offset1, offset2
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
cpdef draw_line(unsigned int [:, :] pic, (int, int) p0, (int, int) p1,
                unsigned int [:, :] brush, int step=1):

    "Draw a line from p0 to p1 using a brush or a single pixel of given color."

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

    with nogil:
        while True:
            if i % step == 0:
                blit(pic, brush, x, y)
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


# cpdef draw_rectangle(LongPicture pic, (int, int) pos, (int, int) size, brush=None, unsigned int color=0,
#                      bint fill=False, int step=1):

#     cdef int x0, y0, w0, h0, x, y, w, h, cols, rows, bw, bh, hw, hh
#     x0, y0 = pos
#     w0, h0 = size

#     # ensure that the rectangle stays within the image borders
#     x = max(0, x0)
#     y = max(0, y0)
#     w = w0 - (x - x0)
#     h = h0 - (y - y0)

#     cols, rows = pic.size
#     w = min(cols - x, w)
#     h = min(rows - y, h)

#     if fill:
#         for i in range(y, min(y+h, rows)):
#             draw_line(pic, (x0, i), (x0+w, i), None, color, step)
#     else:
#         draw_line(pic, pos, (x0+w0, y0), brush, color, step)
#         draw_line(pic, (x0+w0, y0), (x0+w0, y0+h0), brush, color, step)
#         draw_line(pic, (x0+w0, y0+h0), (x0, y0+h0), brush, color, step)
#         draw_line(pic, (x0, y0+h0), pos, brush, color, step)

#     bw = brush.width if brush else 0
#     bh = brush.height if brush else 0

#     return pic.rect.intersect(Rectangle((x, y), (w + bw, h + bh)))


# # cdef horizontal_line(int** image, int y, int xmin, int xmax, int color):
# #     cdef int x
# #     for x in range(xmin, xmax):
# #         image[y][x] = color


# # def vertical_line(image, x, ymin, ymax, color):
# #     cols, rows = image.size
# #     if 0 <= x <= cols:
# #         ymin = max(0, ymin)
# #         ymax = min(rows, ymax)
# #         col = array("B", color * (ymax - ymin))
# #         print ymax-ymin
# #         image.data[4*(ymin*cols+x):4*(ymax*cols+x):4*cols] = col


# cpdef draw_ellipse(LongPicture pic, (int, int) center, (int, int) size, LongPicture brush=None,
#                    unsigned int color=0, bint fill=False):

#     # TODO this does not handle small radii (<5) well
#     # TODO support rotated ellipses

#     cdef int w, h, a, b, x0, y0, a2, b2, error, x, y, stopx, stopy, bw, bh, hw, hh

#     a, b = size
#     if a <= 0 or b <= 0:
#         return None
#     x0, y0 = center

#     a2 = 2*a*a
#     b2 = 2*b*b
#     error = a*a*b

#     x = 0
#     y = b
#     stopy = 0
#     stopx = a2 * b
#     bw = brush.width if brush else 0
#     bh = brush.height if brush else 0

#     w, h = pic.size

#     if not (0 <= x0 < w) or not (0 <= y0 < h):
#         # TODO This should be allowed, but right now would crash
#         return None

#     cdef int xx, yy
#     cdef int topy, boty, lx, rx

#     if b == 0:
#         if fill:
#             lx = min(w-1, max(0, x0 - a))
#             rx = max(0, min(w, x0 + a + 1))
#             draw_line(pic, (lx, y0), (rx, y0), color)
#             rect = Rectangle((x0-a, y0), (2*a+1, 1))
#         else:
#             rect = draw_line(pic, (x0-a, y0), (x0+a+1, y0), brush, color)
#         return pic.rect.intersect(rect)

#     if a == 0:
#         if fill and color:
#             rect = draw_rectangle(pic, (x0, y0-b), (1, 2*b+1), color=color, fill=True)
#         else:
#             rect = draw_line(pic, (x0, y0-b), (x0, y0+b+1), brush, color)
#         return pic.rect.intersect(rect)

#     # TODO Simplify.
#     if fill:
#         while stopy <= stopx:
#             topy = y0 - y
#             boty = y0 + y
#             lx = min(w-1, max(0, x0 - x))
#             rx = max(0, min(w, x0 + x))
#             if topy >= 0:
#                 draw_line(pic, (lx, topy), (rx, topy), None, color)
#             if boty < h:
#                 draw_line(pic, (lx, boty), (rx, boty), None, color)
#             x += 1
#             error -= b2 * (x - 1)
#             stopy += b2
#             if error <= 0:
#                 error += a2 * (y - 1)
#                 y -= 1
#                 stopx -= a2

#         error = b*b*a
#         x = a
#         y = 0
#         stopy = b2 * a
#         stopx = 0

#         while stopy >= stopx:
#             topy = y0 - y
#             boty = y0 + y
#             lx = max(0, x0 - x)
#             rx = min(w, x0 + x)
#             if topy >= 0:
#                 draw_line(pic, (lx, topy), (rx, topy), None, color)
#             if boty < h:
#                 draw_line(pic, (lx, boty), (rx, boty), None, color)
#             y += 1
#             error -= a2 * (y - 1)
#             stopx += a2
#             if error < 0:
#                 error += b2 * (x - 1)
#                 x -= 1
#                 stopy -= b2
#     else:
#         with nogil:
#             # Note: nogil makes a huge differece here since this can be quite slow with
#             # a large brush.
#             while stopy <= stopx:
#                 topy = y0 - y
#                 boty = y0 + y
#                 xx = x0 + x
#                 yy = y0 + y
#                 if (xx + bw) >= 0 and xx < w and (yy + bh) >= 0 and yy < h:
#                     pic.paste(brush, xx, yy, True)
#                 xx = x0 - x
#                 yy = y0 + y
#                 if xx + bw >= 0 and xx < w and yy + bh >= 0 and yy < h:
#                     pic.paste(brush, xx, yy, True)
#                 xx = x0 - x
#                 yy = y0 - y
#                 if xx + bw >= 0 and xx < w and yy + bh >= 0 and yy < h:
#                     pic.paste(brush, xx, yy, True)
#                 xx = x0 + x
#                 yy = y0 - y
#                 if xx + bw >= 0 and xx < w and yy + bh >= 0 and yy < h:
#                     pic.paste(brush, xx, yy, True)
#                 x += 1
#                 error -= b2 * (x - 1)
#                 stopy += b2
#                 if error <= 0:
#                     error += a2 * (y - 1)
#                     y -= 1
#                     stopx -= a2

#             error = b*b*a
#             x = a
#             y = 0
#             stopy = b2 * a
#             stopx = 0

#             while stopy >= stopx:
#                 topy = y0 - y
#                 boty = y0 + y
#                 xx = x0 + x
#                 yy = y0 + y
#                 if xx + bw >= 0 and xx < w and yy + bh >= 0 and yy < h:
#                     pic.paste(brush, xx, yy, True)
#                 xx = x0 - x
#                 yy = y0 + y
#                 if xx + bw >= 0 and xx < w and yy + bh >= 0 and yy < h:
#                     pic.paste(brush, xx, yy, True)
#                 xx = x0 - x
#                 yy = y0 - y
#                 if xx + bw >= 0 and xx < w and yy + bh >= 0 and yy < h:
#                     pic.paste(brush, xx, yy, True)
#                 xx = x0 + x
#                 yy = y0 - y
#                 if xx + bw >= 0 and xx < w and yy + bh >= 0 and yy < h:
#                     pic.paste(brush, xx, yy, True)

#                 y += 1
#                 error -= a2 * (y - 1)
#                 stopx += a2
#                 if error < 0:
#                     error += b2 * (x - 1)
#                     x -= 1
#                     stopy -= b2

#     return pic.rect.intersect(Rectangle((x0-a-1, y0-b-1), (2*a+bw+2, 2*b+bh+2)))


# cpdef draw_fill(LongPicture pic, (int, int) point, unsigned int color):

#     # TODO kind of slow, and requires the GIL.

#     cdef int startx, starty, w, h
#     startx, starty = point
#     cdef list stack = [point]  # TODO maybe find some more C friendly way of keeping a stack
#     w, h = pic.size
#     cdef unsigned int start_col = pic[startx, starty] & 0xFF

#     if start_col == color & 0xFF:
#         return

#     cdef int x, y, xmin, xmax, ymin, ymax, xstart
#     cdef bint reach_top, reach_bottom
#     xmin, xmax = w, 0
#     ymin, ymax = h, 0

#     while stack:
#         x, y = stack.pop()
#         # search left
#         while x >= 0 and start_col == pic[x, y]:
#             x -= 1
#         x += 1
#         reach_top = reach_bottom = False

#         # search right
#         while x < w and pic[x, y] == start_col:
#             pic[x, y] = color  # color this pixel
#             xmin, xmax = min(xmin, x), max(xmax, x)
#             ymin, ymax = min(ymin, y), max(ymax, y)
#             if 0 < y < h - 1:

#                 # check pixel above
#                 if start_col == pic[x, y-1]:
#                     if not reach_top:
#                         stack.append((x, y-1))  # add previous line
#                         reach_top = True
#                 elif reach_top:
#                     reach_top = False

#                 # check pixel below
#                 if start_col == pic[x, y+1]:
#                     if not reach_bottom:
#                         stack.append((x, y+1))  # add next line
#                         reach_bottom = True
#                 elif reach_bottom:
#                     reach_bottom = False
#             x += 1

#     return Rectangle((xmin, ymin), (xmax-xmin+1, ymax-ymin+1))
