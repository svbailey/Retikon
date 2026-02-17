from PIL import Image

from retikon_core.ingestion import ocr


def test_ocr_result_from_image_filters_low_confidence_tokens(monkeypatch):
    class FakePytesseract:
        class Output:
            DICT = object()

        @staticmethod
        def image_to_data(_image, output_type=None):
            return {
                "text": ["INV", "12345", "noise"],
                "conf": ["95", "88", "10"],
            }

        @staticmethod
        def image_to_string(_image):
            return ""

    monkeypatch.setattr(ocr, "_load_pytesseract", lambda: FakePytesseract())
    image = Image.new("RGB", (8, 8), color=(255, 255, 255))

    result = ocr.ocr_result_from_image(
        image,
        min_confidence=60,
        min_text_len=3,
    )

    assert result.text == "INV 12345"
    assert result.conf_avg == 92
    assert result.kept_tokens == 2
    assert result.raw_tokens == 3


def test_ocr_result_from_image_honors_min_text_len(monkeypatch):
    class FakePytesseract:
        class Output:
            DICT = object()

        @staticmethod
        def image_to_data(_image, output_type=None):
            return {
                "text": ["AB"],
                "conf": ["99"],
            }

        @staticmethod
        def image_to_string(_image):
            return ""

    monkeypatch.setattr(ocr, "_load_pytesseract", lambda: FakePytesseract())
    image = Image.new("RGB", (8, 8), color=(255, 255, 255))

    result = ocr.ocr_result_from_image(
        image,
        min_confidence=0,
        min_text_len=4,
    )

    assert result.text == ""
    assert result.conf_avg is None
    assert result.kept_tokens == 0
    assert result.raw_tokens == 1

