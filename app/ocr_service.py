"""Сервис оптического распознавания символов (OCR) для сканов документов и изображений.
Поддерживает переключение между тремя движками:
1. RapidOCR (на базе ONNX Runtime) — быстрый, легкий (~15 МБ), моментальный старт.
2. EasyOCR (на базе PyTorch) — мощные сверточные нейросети для сложных документов.
3. Tesseract OCR — классический движок.
"""

import io
import logging
from typing import Any, List, Optional
from PIL import Image

logger = logging.getLogger(__name__)

# Глобальные инстансы для быстрого переиспользования
_rapid_ocr_instance: Optional[Any] = None
_easy_ocr_readers: dict[str, Any] = {}


def get_rapid_ocr():
    global _rapid_ocr_instance
    if _rapid_ocr_instance is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _rapid_ocr_instance = RapidOCR()
            logger.info("RapidOCR успешно инициализирован.")
        except Exception as e:
            logger.error(f"Ошибка инициализации RapidOCR: {e}")
            raise
    return _rapid_ocr_instance


def get_easy_ocr_reader(lang: str = "rus+eng"):
    global _easy_ocr_readers
    langs = []
    if "rus" in lang:
        langs.append("ru")
    if "eng" in lang or not langs:
        langs.append("en")

    lang_key = "+".join(langs)
    if lang_key not in _easy_ocr_readers:
        try:
            import easyocr
            logger.info(f"Инициализация EasyOCR Reader (языки: {langs})...")
            _easy_ocr_readers[lang_key] = easyocr.Reader(langs, gpu=False)
        except Exception as e:
            logger.error(f"Ошибка инициализации EasyOCR: {e}")
            raise
    return _easy_ocr_readers[lang_key]


class OCRService:
    """Сервис распознавания текста и табличных структур из сканов."""

    @staticmethod
    def recognize_image(image: Image.Image, engine: str = "rapidocr", lang: str = "rus+eng") -> list[dict[str, Any]]:
        """Распознает текст на изображении с возвратом координат блоков:
        [{'text': str, 'box': [[x1, y1], [x2, y2], [x3, y3], [x4, y4]], 'score': float}]
        """
        results = []
        engine = (engine or "rapidocr").lower()

        if engine == "rapidocr":
            try:
                ocr = get_rapid_ocr()
                import numpy as np
                img_np = np.array(image.convert("RGB"))
                ocr_result, _ = ocr(img_np)
                if ocr_result:
                    for item in ocr_result:
                        box, text, score = item
                        if text and text.strip():
                            results.append({
                                "text": text.strip(),
                                "box": box,
                                "score": float(score) if score is not None else 1.0,
                            })
            except Exception as e:
                logger.warning(f"Ошибка RapidOCR: {e}, fallback на Tesseract...")
                return OCRService.recognize_image(image, engine="tesseract", lang=lang)

        elif engine == "easyocr":
            try:
                reader = get_easy_ocr_reader(lang=lang)
                import numpy as np
                img_np = np.array(image.convert("RGB"))
                ocr_result = reader.readtext(img_np)
                if ocr_result:
                    for item in ocr_result:
                        box, text, score = item
                        if text and text.strip():
                            results.append({
                                "text": text.strip(),
                                "box": box,
                                "score": float(score) if score is not None else 1.0,
                            })
            except Exception as e:
                logger.warning(f"Ошибка EasyOCR: {e}, fallback на RapidOCR...")
                return OCRService.recognize_image(image, engine="rapidocr", lang=lang)

        elif engine == "tesseract":
            try:
                import pytesseract
                tess_lang = "rus+eng" if "rus" in lang else "eng"
                data = pytesseract.image_to_data(image, lang=tess_lang, output_type=pytesseract.Output.DICT)
                n_boxes = len(data["text"])
                for i in range(n_boxes):
                    txt = data["text"][i].strip()
                    conf = float(data["conf"][i])
                    if txt and conf > 20:
                        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
                        box = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
                        results.append({
                            "text": txt,
                            "box": box,
                            "score": conf / 100.0,
                        })
            except Exception as e:
                logger.error(f"Ошибка Tesseract OCR: {e}")

        return results

    @staticmethod
    def reconstruct_table_from_ocr(boxes: list[dict[str, Any]], y_tolerance: int = 15) -> list[list[str]]:
        """Восстанавливает сетку таблицы из распознанных боксов по координатам."""
        if not boxes:
            return []

        items = []
        for b in boxes:
            box = b["box"]
            y_center = sum(pt[1] for pt in box) / len(box)
            x_left = min(pt[0] for pt in box)
            items.append({
                "text": b["text"],
                "x": x_left,
                "y": y_center,
            })

        items.sort(key=lambda item: item["y"])

        rows: list[list[dict[str, Any]]] = []
        current_row: list[dict[str, Any]] = []
        current_row_y: Optional[float] = None

        for item in items:
            if current_row_y is None or abs(item["y"] - current_row_y) <= y_tolerance:
                current_row.append(item)
                current_row_y = sum(x["y"] for x in current_row) / len(current_row)
            else:
                rows.append(current_row)
                current_row = [item]
                current_row_y = item["y"]

        if current_row:
            rows.append(current_row)

        grid: list[list[str]] = []
        for row_items in rows:
            row_items.sort(key=lambda x: x["x"])
            grid.append([x["text"] for x in row_items])

        max_cols = max(len(r) for r in grid) if grid else 0
        normalized_grid = []
        for r in grid:
            if len(r) < max_cols:
                r.extend([""] * (max_cols - len(r)))
            normalized_grid.append(r)

        return normalized_grid
