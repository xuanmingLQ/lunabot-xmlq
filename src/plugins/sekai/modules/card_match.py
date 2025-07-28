import cv2
from datetime import datetime
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple, Union
import math

@dataclass
class BBox:
    x: int
    y: int
    w: int
    h: int
    
    def area(self):
        return self.w * self.h
    def p1(self) -> Tuple[int, int]:
        return (self.x, self.y)
    def p2(self) -> Tuple[int, int]:
        return (self.x + self.w, self.y + self.h)
    def center(self) -> Tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)
    def __str__(self):
        return f"BBox(x={self.x}, y={self.y}, w={self.w}, h={self.h})"
    def __iter__(self):
        yield self.x
        yield self.y
        yield self.w
        yield self.h

@dataclass
class Grid:
    start_x: int
    start_y: int
    size: int
    sep: int
    rows: int
    cols: int
    img: np.ndarray = None
    valid_points: List[Tuple[int, int]] = field(default_factory=list)
    def get_all_points(self):
        for i in range(self.rows):
            for j in range(self.cols):
                cx = self.start_x + self.sep * j
                cy = self.start_y + self.sep * i
                yield (cx, cy)
    def get_valid_bboxes(self):
        for p in self.valid_points:
            yield BBox(p[0] - self.size // 2, p[1] - self.size // 2, self.size, self.size)
    def get_grid_images(self):
        for bbox in self.get_valid_bboxes():
            yield self.img[bbox.y:bbox.y+bbox.h, bbox.x:bbox.x+bbox.w]
    def __len__(self):
        return len(self.valid_points)


