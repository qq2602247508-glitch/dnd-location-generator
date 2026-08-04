from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable, Iterator

Cell = tuple[int, int]


@dataclass(frozen=True)
class CellMask:
    cells: frozenset[Cell]

    @classmethod
    def empty(cls) -> "CellMask":
        return cls(frozenset())

    @classmethod
    def from_cells(cls, cells: Iterable[Cell]) -> "CellMask":
        return cls(frozenset((int(row), int(col)) for row, col in cells))

    @classmethod
    def rect(cls, row: int, col: int, height: int, width: int) -> "CellMask":
        return cls.from_cells(
            (r, c)
            for r in range(row, row + height)
            for c in range(col, col + width)
        )

    @classmethod
    def path(cls, points: list[Cell], radius: int = 0) -> "CellMask":
        cells: set[Cell] = set()
        for start, end in zip(points, points[1:]):
            cells.update(_line(start, end))
        if points:
            cells.add(points[-1])
        result = cls.from_cells(cells)
        return result.dilate(radius) if radius else result

    def __or__(self, other: "CellMask") -> "CellMask":
        return CellMask(self.cells | other.cells)

    def __and__(self, other: "CellMask") -> "CellMask":
        return CellMask(self.cells & other.cells)

    def __sub__(self, other: "CellMask") -> "CellMask":
        return CellMask(self.cells - other.cells)

    def __len__(self) -> int:
        return len(self.cells)

    def sorted_cells(self) -> list[Cell]:
        return sorted(self.cells)

    def dilate(self, radius: int = 1) -> "CellMask":
        if radius <= 0:
            return self
        points = set(self.cells)
        frontier = set(self.cells)
        for _ in range(radius):
            frontier = {
                neighbor
                for row, col in frontier
                for neighbor in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1))
            } - points
            points.update(frontier)
        return CellMask.from_cells(points)

    def clipped(self, height: int, width: int) -> "CellMask":
        return CellMask.from_cells((r, c) for r, c in self.cells if 0 <= r < height and 0 <= c < width)

    def components(self) -> list["CellMask"]:
        remaining = set(self.cells)
        result: list[CellMask] = []
        while remaining:
            start = min(remaining)
            seen = {start}
            queue = deque([start])
            while queue:
                row, col = queue.popleft()
                for point in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
                    if point in remaining and point not in seen:
                        seen.add(point)
                        queue.append(point)
            remaining.difference_update(seen)
            result.append(CellMask.from_cells(seen))
        return result

    def boundary_edges(self) -> list[tuple[Cell, Cell]]:
        edges: list[tuple[Cell, Cell]] = []
        for row, col in sorted(self.cells):
            for neighbor in ((row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)):
                if neighbor not in self.cells:
                    edges.append(((row, col), neighbor))
        return edges

    def to_rle(self) -> dict[str, object]:
        runs: list[list[int]] = []
        by_row: dict[int, list[int]] = {}
        for row, col in sorted(self.cells):
            by_row.setdefault(row, []).append(col)
        for row, cols in sorted(by_row.items()):
            start = previous = cols[0]
            for col in cols[1:]:
                if col != previous + 1:
                    runs.append([row, start, previous - start + 1])
                    start = col
                previous = col
            runs.append([row, start, previous - start + 1])
        return {"encoding": "rle-v1", "runs": runs}

    @classmethod
    def from_rle(cls, payload: dict[str, object]) -> "CellMask":
        if payload.get("encoding") != "rle-v1":
            raise ValueError("unsupported cell-mask encoding")
        runs = payload.get("runs")
        if not isinstance(runs, list):
            raise ValueError("cell-mask runs must be a list")
        return cls.from_cells(
            (int(row), col)
            for row, start, length in runs
            for col in range(int(start), int(start) + int(length))
        )


def neighbors(cell: Cell) -> Iterator[Cell]:
    row, col = cell
    yield row - 1, col
    yield row + 1, col
    yield row, col - 1
    yield row, col + 1


def _line(start: Cell, end: Cell) -> set[Cell]:
    """Integer Bresenham line in row/column space."""
    row0, col0 = start
    row1, col1 = end
    x0, y0, x1, y1 = col0, row0, col1, row1
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    error = dx + dy
    result: set[Cell] = set()
    while True:
        result.add((y0, x0))
        if x0 == x1 and y0 == y1:
            break
        twice = 2 * error
        if twice >= dy:
            error += dy
            x0 += sx
        if twice <= dx:
            error += dx
            y0 += sy
    return result

