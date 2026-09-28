"""
Image validation tests — run with: python3 tests/test_image_validation.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from PIL import Image

from backend.agents.base import AgentError
from backend.agents.orchestrator import Orchestrator
from backend.core.image_validation import ImageValidationError, validate_image
from backend.memory.store import FarmMemory
from backend.vision.preprocessing import pil_to_bgr

SAMPLES = REPO_ROOT / "data" / "samples"


class TestImageValidationInIsolation(unittest.TestCase):
    def test_real_sample_images_all_pass(self):
        for name in ["tomato_healthy", "tomato_mild", "tomato_moderate", "tomato_severe"]:
            img = pil_to_bgr(Image.open(SAMPLES / "crop" / f"{name}.jpg"))
            validate_image(img)  # should not raise

    def test_none_is_rejected(self):
        with self.assertRaises(ImageValidationError):
            validate_image(None)

    def test_too_small_is_rejected(self):
        with self.assertRaises(ImageValidationError):
            validate_image(np.random.randint(0, 255, (10, 10, 3), dtype=np.uint8))

    def test_blank_black_frame_is_rejected(self):
        with self.assertRaises(ImageValidationError):
            validate_image(np.zeros((200, 200, 3), dtype=np.uint8))

    def test_blank_white_frame_is_rejected(self):
        with self.assertRaises(ImageValidationError):
            validate_image(np.full((200, 200, 3), 255, dtype=np.uint8))

    def test_grayscale_2d_array_is_rejected(self):
        with self.assertRaises(ImageValidationError):
            validate_image(np.random.randint(0, 255, (200, 200), dtype=np.uint8))

    def test_wrong_channel_count_is_rejected(self):
        with self.assertRaises(ImageValidationError):
            validate_image(np.random.randint(0, 255, (200, 200, 4), dtype=np.uint8))

    def test_absurdly_large_is_rejected(self):
        with self.assertRaises(ImageValidationError):
            validate_image(np.zeros((9000, 9000, 3), dtype=np.uint8))

    def test_error_messages_are_farmer_readable(self):
        # Spot-check that messages don't leak implementation jargon a
        # farmer wouldn't understand.
        try:
            validate_image(np.zeros((200, 200, 3), dtype=np.uint8))
        except ImageValidationError as exc:
            self.assertNotIn("stddev", str(exc).lower())
            self.assertNotIn("ndarray", str(exc).lower())


class TestImageValidationThroughRealVisionAgent(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.memory = FarmMemory(db_path=Path(self._tmpdir.name) / "test.db")
        self.orchestrator = Orchestrator.default(memory=self.memory)
        farmer_id = self.memory.get_or_create_farmer("Test Farmer")
        self.farm_id = self.memory.get_or_create_farm(farmer_id, "Test Farm")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_blank_frame_is_rejected_before_reaching_cv_pipeline(self):
        blank = np.zeros((300, 300, 3), dtype=np.uint8)
        with self.assertRaises(AgentError) as ctx:
            self.orchestrator.handle_crop_scan(self.farm_id, blank, "FIELD-01", "Tomato", is_demo=True)
        self.assertTrue(ctx.exception.retryable)
        # And nothing should have been written to Farm Memory for a
        # rejected image — no half-processed scan record.
        field_id = self.memory.get_or_create_field(self.farm_id, "FIELD-01", "Tomato")
        self.assertEqual(len(self.memory.get_field_history(field_id)), 0)

    def test_livestock_scan_also_rejects_a_blank_frame(self):
        blank = np.zeros((300, 300, 3), dtype=np.uint8)
        with self.assertRaises(AgentError):
            self.orchestrator.handle_livestock_scan(self.farm_id, blank, "COW-001", "Cow", is_demo=True)

    def test_real_photo_still_works_normally_after_the_validation_gate(self):
        # The gate must not interfere with legitimate photos — full
        # regression of the existing happy path.
        img = pil_to_bgr(Image.open(SAMPLES / "crop" / "tomato_severe.jpg"))
        rec = self.orchestrator.handle_crop_scan(self.farm_id, img, "FIELD-02", "Tomato", is_demo=True)
        self.assertEqual(rec.source_agent, "vision_agent")


if __name__ == "__main__":
    unittest.main(verbosity=2)
