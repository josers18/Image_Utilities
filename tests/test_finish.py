import tempfile
import threading
import unittest
from pathlib import Path

from PIL import Image

from app.config import MAX_EDGE
from app.engine import Engine, JobSpec, Reporter
from app.finish import (
    Options,
    TooLarge,
    adjust_edge,
    crop_to_subject,
    disambiguate,
    file_suffix,
    finish_image,
    fit_image,
    place_file,
    planned_filename,
    renamed_stem,
    target_size,
    write_outputs,
)
from app.jobs import Store
from app.naming import output_name


def _square(size: int, color) -> Image.Image:
    return Image.new("RGBA", (size, size), color)


class NamingFinishTests(unittest.TestCase):
    def test_output_names_for_the_new_tasks(self):
        self.assertEqual(output_name("photo", "resize", 4), "photo.resized.png")
        self.assertEqual(output_name("photo", "resize", 4, ".webp"), "photo.resized.webp")
        self.assertEqual(output_name("photo", "convert", 4, ".svg"), "photo.svg")
        self.assertEqual(output_name("photo", "rename", 4, ".jpg"), "photo.jpg")

    def test_rename_pattern_numbers_and_strips_path_marks(self):
        options = Options(prefix="../shot-", suffix="!", find="cat", replace="dog", number=True, digits=3)
        self.assertEqual(renamed_stem("cat", options, 1), "shot-dog!-002")
        self.assertEqual(disambiguate(["Cat", "cat", "Cat"]), ["Cat", "cat-2", "Cat-3"])

    def test_suffix_follows_the_original_when_the_type_stays(self):
        options = Options(task="resize", format="same")
        self.assertEqual(file_suffix(options, Path("a.JPEG")), ".jpg")
        self.assertEqual(file_suffix(options, Path("a.tiff")), ".png")
        self.assertEqual(file_suffix(Options(format="jpeg"), Path("a.png")), ".jpg")
        self.assertEqual(
            planned_filename("cat", Options(task="resize", format="webp"), 0, Path("cat.png")),
            "cat.resized.webp",
        )

    def test_normalize_picks_a_usable_default_for_each_task(self):
        resize = Options.from_dict({"task": "resize", "fit": "none", "fit_a": 0})
        self.assertEqual(resize.fit, "long")
        self.assertEqual(resize.fit_a, 2048)
        convert = Options.from_dict({"task": "convert", "format": "same"})
        self.assertEqual(convert.format, "webp")
        rename = Options.from_dict({"task": "rename", "format": "jpeg", "also_webp": True})
        self.assertEqual(rename.format, "same")
        self.assertFalse(rename.also_webp)
        webp = Options.from_dict({"format": "webp", "also_webp": True})
        self.assertFalse(webp.also_webp)
        self.assertEqual(Options.from_dict({"task": "nope"}).task, "both")


class SizeTests(unittest.TestCase):
    def test_target_sizes(self):
        self.assertEqual(target_size(100, 50, "long", 20, 0, False)[:2], (20, 10))
        self.assertEqual(target_size(100, 50, "width", 40, 0, False)[:2], (40, 20))
        self.assertEqual(target_size(100, 50, "height", 40, 0, False)[:2], (80, 40))
        self.assertEqual(target_size(100, 50, "box", 30, 30, False)[:2], (30, 15))
        self.assertEqual(target_size(100, 50, "percent", 50, 0, False)[:2], (50, 25))
        width, height, note = target_size(100, 50, "long", 400, 0, True)
        self.assertEqual((width, height), (100, 50))
        self.assertIn("smaller", note)

    def test_target_size_refuses_a_huge_result(self):
        with self.assertRaises(TooLarge):
            target_size(MAX_EDGE, MAX_EDGE, "percent", 200, 0, False)

    def test_convert_ignores_a_leftover_size(self):
        image = Image.new("RGB", (20, 10), (10, 20, 30))
        options = Options(task="convert", fit="long", fit_a=4, format="png")
        finished, _meta, _notes = finish_image(image, {}, options)
        self.assertEqual(finished.size, (20, 10))


class MatteTests(unittest.TestCase):
    def test_trim_adds_padding_around_the_subject(self):
        image = _square(20, (0, 0, 0, 0))
        image.paste(_square(4, (255, 0, 0, 255)), (1, 2))
        cropped = crop_to_subject(image, 3)
        self.assertEqual(cropped.size, (10, 10))
        self.assertEqual(cropped.getpixel((3, 3)), (255, 0, 0, 255))
        self.assertEqual(cropped.getpixel((0, 0))[3], 0)

    def test_tighter_edge_shrinks_and_holes_close(self):
        blob = _square(7, (0, 0, 0, 0))
        blob.paste(_square(3, (0, 0, 0, 255)), (2, 2))
        tight = adjust_edge(blob, "tight", False).getchannel("A")
        self.assertEqual(tight.getpixel((3, 3)), 255)
        self.assertEqual(tight.getpixel((2, 2)), 0)

        hole = _square(9, (0, 0, 0, 255))
        hole.putpixel((4, 4), (0, 0, 0, 0))
        filled = adjust_edge(hole, "normal", True).getchannel("A")
        self.assertEqual(filled.getpixel((4, 4)), 255)

    def test_jpeg_flattens_and_webp_keeps_the_matte(self):
        image = _square(8, (0, 0, 0, 0))
        image.putpixel((1, 1), (255, 0, 0, 255))
        flat, _meta, notes = finish_image(image, {}, Options(task="convert", format="jpeg"))
        self.assertEqual(flat.mode, "RGB")
        self.assertEqual(flat.getpixel((0, 0)), (255, 255, 255))
        self.assertTrue(any("JPEG" in note for note in notes))

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            webp, _notes = write_outputs(image, {}, root, "mark.webp", Options(format="webp", quality=90))
            saved = Image.open(webp)
            self.assertEqual(saved.mode, "RGBA")
            self.assertEqual(saved.getpixel((0, 0))[3], 0)
            self.assertGreater(saved.getpixel((1, 1))[3], 200)

    def test_svg_trace_and_webp_sibling(self):
        image = _square(48, (255, 255, 255, 255))
        image.paste(_square(20, (200, 30, 30, 255)), (4, 4))
        image.paste(_square(16, (20, 40, 180, 255)), (26, 24))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            dest, notes = write_outputs(
                image, {}, root, "mark.svg", Options(format="svg", also_webp=True, quality=80)
            )
            text = dest.read_text(encoding="utf-8", errors="replace").lower()
            self.assertIn("<svg", text)
            self.assertTrue((root / "mark.webp").is_file())
            self.assertTrue(any(note.startswith("Also saved") for note in notes))


class PlaceTests(unittest.TestCase):
    def test_rename_moves_and_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "cat.png"
            source.write_bytes(b"png")
            taken = root / "dog.png"
            taken.write_bytes(b"keep")
            moved = place_file(source, root, "dog.png", move=True)
            self.assertEqual(moved.name, "dog-2.png")
            self.assertFalse(source.exists())
            self.assertEqual(taken.read_bytes(), b"keep")
            same = place_file(moved, root, moved.name, move=True)
            self.assertEqual(same, moved)

    def test_copy_leaves_the_original(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "cat.png"
            source.write_bytes(b"png")
            out = root / "out"
            copied = place_file(source, out, "cat.png", move=False)
            self.assertTrue(source.is_file())
            self.assertEqual(copied.read_bytes(), b"png")


class PipelineTests(unittest.TestCase):
    def test_resize_writes_the_finished_size(self):
        engine = Engine()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "wide.png"
            Image.new("RGB", (40, 20), (20, 40, 60)).save(source)
            spec = JobSpec(
                source=source,
                dest_dir=root,
                dest_name="wide.resized.png",
                task="resize",
                scale=4,
                look="photo",
                preview_before=root / "before.jpg",
                preview_after=root / "after.png",
                thumb=root / "thumb.jpg",
                options=Options(task="resize", fit="long", fit_a=10, format="png"),
            )
            result = engine.process_file(spec, Reporter(lambda _phase, _frac: None), threading.Event())
            self.assertEqual((result.width, result.height), (10, 5))
            with Image.open(result.output) as saved:
                self.assertEqual(saved.size, (10, 5))
            self.assertTrue((root / "before.jpg").is_file())

    def test_store_resizes_converts_and_renames_without_touching_pictures(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pictures = root / "pictures"
            pictures.mkdir()
            red = pictures / "red.png"
            blue = pictures / "blue.png"
            Image.new("RGB", (30, 10), (200, 0, 0)).save(red)
            Image.new("RGB", (30, 10), (0, 0, 200)).save(blue)
            store = Store()
            store.settings.path = root / "settings.json"
            store.settings.output_dir = root / "out"
            store.add_paths([red], subfolders=False)
            store.start(Options(task="resize", fit="width", fit_a=15, save="folder", format="jpeg", quality=85))
            self.assertIsNotNone(store.thread)
            assert store.thread is not None
            store.thread.join(20)
            done = store.batch.items[0]
            self.assertEqual(done.status, "done", done.message)
            self.assertTrue(red.is_file())
            with Image.open(done.output) as saved:
                self.assertEqual(saved.size, (15, 5))
                self.assertEqual(saved.format, "JPEG")

            mark = pictures / "mark.png"
            Image.new("RGBA", (24, 24), (0, 180, 0, 255)).save(mark)
            store.add_paths([mark], subfolders=False)
            store.start(Options(task="convert", format="webp", save="folder", quality=80, fit="long", fit_a=4))
            assert store.thread is not None
            store.thread.join(20)
            converted = store.batch.items[0]
            self.assertEqual(converted.status, "done", converted.message)
            with Image.open(converted.output) as saved:
                self.assertEqual(saved.size, (24, 24))
            self.assertEqual(converted.output.suffix, ".webp")

            store.add_paths([red, blue], subfolders=False)
            store.start(
                Options(
                    task="rename",
                    save="beside",
                    prefix="web-",
                    number=True,
                    number_start=1,
                    digits=2,
                    format="png",
                )
            )
            assert store.thread is not None
            store.thread.join(20)
            items = {item.name: item for item in store.batch.items}
            self.assertEqual(items["web-red-01.png"].note, "Renamed the file.")
            self.assertEqual(items["web-blue-02.png"].note, "Renamed the file.")
            self.assertFalse(red.exists())
            self.assertFalse(blue.exists())
            self.assertTrue((pictures / "web-red-01.png").is_file())
            self.assertTrue((pictures / "web-blue-02.png").is_file())


class FitImageTests(unittest.TestCase):
    def test_lanczos_resize_changes_the_pixel_size(self):
        image = Image.new("RGB", (12, 8), (1, 2, 3))
        resized, note = fit_image(image, Options(fit="percent", fit_a=50))
        self.assertEqual(resized.size, (6, 4))
        self.assertEqual(note, "")


if __name__ == "__main__":
    unittest.main()
