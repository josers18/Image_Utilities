import tempfile
import unittest
from pathlib import Path

from app.naming import format_bytes, list_images, output_name, safe_filename, unique_path
from app.tiles import iter_tiles


class NamingTests(unittest.TestCase):
    def test_output_names(self):
        self.assertEqual(output_name("photo", "cutout", 4), "photo.cutout.png")
        self.assertEqual(output_name("photo", "upscale", 2), "photo.x2.png")
        self.assertEqual(output_name("photo", "both", 4), "photo.cutout.x4.png")

    def test_unique_path_skips_existing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "photo.cutout.png"
            path.write_bytes(b"x")
            self.assertEqual(unique_path(path).name, "photo.cutout-2.png")

    def test_list_images_skips_hidden_text_and_can_include_subfolders(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "a.JPG").write_bytes(b"x")
            (root / "notes.txt").write_bytes(b"x")
            (root / ".secret.png").write_bytes(b"x")
            sub = root / "sub"
            sub.mkdir()
            (sub / "b.png").write_bytes(b"x")
            files, truncated = list_images(root, subfolders=False, limit=10)
            self.assertEqual([path.name for path in files], ["a.JPG"])
            self.assertFalse(truncated)
            files, _truncated = list_images(root, subfolders=True, limit=10)
            self.assertEqual(sorted(path.name for path in files), ["a.JPG", "b.png"])

    def test_safe_filename_strips_directories(self):
        self.assertEqual(safe_filename("../../etc/photo.jpg"), "photo.jpg")
        self.assertEqual(safe_filename(""), "image")

    def test_format_bytes(self):
        self.assertEqual(format_bytes(12), "12 B")
        self.assertEqual(format_bytes(2048), "2 KB")
        self.assertEqual(format_bytes(1_500_000), "1.4 MB")


class TileTests(unittest.TestCase):
    def test_inner_rectangles_cover_the_image_once(self):
        for width, height in ((1, 1), (16, 40), (512, 512), (513, 200), (1000, 800), (2049, 3)):
            cover = [[0 for _ in range(width)] for _ in range(height)]
            tiles = iter_tiles(width, height, 512, 24)
            self.assertTrue(tiles)
            for tile in tiles:
                self.assertLessEqual(0, tile.win_left)
                self.assertLessEqual(tile.win_right, width)
                self.assertLessEqual(tile.win_left, tile.left)
                self.assertLessEqual(tile.right, tile.win_right)
                self.assertLessEqual(tile.win_top, tile.top)
                self.assertLessEqual(tile.bottom, tile.win_bottom)
                for y in range(tile.top, tile.bottom):
                    for x in range(tile.left, tile.right):
                        cover[y][x] += 1
            self.assertTrue(all(cell == 1 for row in cover for cell in row))


if __name__ == "__main__":
    unittest.main()

