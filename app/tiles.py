from dataclasses import dataclass


@dataclass(frozen=True)
class Tile:
    """A window the model sees, and the inner rectangle copied into the result.

    The window is larger than the inner rectangle by `pad` pixels so the seam
    between tiles is computed with some neighboring context, then thrown away.
    """

    win_left: int
    win_top: int
    win_right: int
    win_bottom: int
    left: int
    top: int
    right: int
    bottom: int


def iter_tiles(width: int, height: int, tile: int, pad: int) -> list[Tile]:
    if width < 1 or height < 1:
        return []
    if tile < 1:
        raise ValueError("tile size must be at least 1")
    if pad < 0:
        raise ValueError("pad must be zero or more")

    tiles: list[Tile] = []
    y = 0
    while y < height:
        x = 0
        bottom = min(y + tile, height)
        while x < width:
            right = min(x + tile, width)
            tiles.append(
                Tile(
                    win_left=max(x - pad, 0),
                    win_top=max(y - pad, 0),
                    win_right=min(right + pad, width),
                    win_bottom=min(bottom + pad, height),
                    left=x,
                    top=y,
                    right=right,
                    bottom=bottom,
                )
            )
            x = right
        y = bottom
    return tiles
