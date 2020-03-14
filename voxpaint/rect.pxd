cdef class Rectangle:
    cdef readonly (int, int) position
    cdef readonly (int, int) size
    cdef readonly int x, y, height, width
    cdef readonly int left, right, top, bottom
    cdef readonly (int, int) topleft, bottomright

    cpdef Rectangle copy(self)
    cpdef Rectangle intersect(self, Rectangle other)
    cpdef Rectangle unite(self, Rectangle other)
    cpdef Rectangle offset(self, (int, int) point)
    # cdef (int, int, int, int) get_points(self)
    # cpdef (int, int, int, int) points(self)
    # cpdef (int, int, int, int) box(self)
    cpdef Rectangle expanded(self, (int, int) point)
    cpdef int area(self)
    cpdef as_slice(self)

cpdef Rectangle from_points(list pts)
cpdef Rectangle cover(list rects)
