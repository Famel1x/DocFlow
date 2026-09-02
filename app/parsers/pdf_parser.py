"""Парсер PDF документов с интеллектуальным детектированием сканов и OCR."""

import io
import logging
import fitz  # PyMuPDF
import pdfplumber
from PIL import Image
from typing import List, Dict, Any

from app.parsers.base import BaseParser
from app.ocr_service import OCRService
from app.storage import storage

logger = logging.getLogger(__name__)


class PDFParser(BaseParser):
    def parse(self) -> List[Dict[str, Any]]:
        content = []

        # Получаем настройки OCR из конфигурации
        settings = storage.get_settings()
        ocr_enabled = getattr(settings, "ocr_enabled", True)

        ocr_engine = getattr(settings, "ocr_engine", "rapidocr")
        ocr_lang = getattr(settings, "ocr_lang", "rus+eng")

        # 1. Сначала пробуем стандартный парсинг через pdfplumber
        has_text_or_tables = False
        plumber_content = []

        try:
            with pdfplumber.open(self.file_path) as pdf:
                for page in pdf.pages:
                    tables = page.find_tables()
                    table_bboxes = [table.bbox for table in tables]

                    for table in tables:
                        extracted_table = table.extract()
                        if extracted_table:
                            clean_table = [
                                [str(cell).strip() if cell is not None else "" for cell in row]
                                for row in extracted_table
                            ]
                            if any(any(c for c in row) for row in clean_table):
                                plumber_content.append({
                                    "type": "table",
                                    "value": clean_table
                                })
                                has_text_or_tables = True

                    def not_within_bboxes(obj):
                        if obj.get("object_type") != "char":
                            return True
                        for (x0, top, x1, bottom) in table_bboxes:
                            if (obj["x0"] >= x0 and obj["x1"] <= x1 and
                                obj["top"] >= top and obj["bottom"] <= bottom):
                                return False
                        return True

                    filtered_page = page.filter(not_within_bboxes)
                    text = filtered_page.extract_text()
                    if text and text.strip():
                        plumber_content.append({"type": "text", "value": text.strip()})
                        has_text_or_tables = True

        except Exception as e:
            logger.warning(f"pdfplumber столкнулся с ошибкой: {e}")

        # Если текстовый слой найден и содержит данные — используем его
        if has_text_or_tables and plumber_content:
            return plumber_content

        # 2. Если в PDF нет цифрового слоя (сканированный документ / растровые изображения),
        # запускаем оптическое распознавание символов (OCR)
        if not ocr_enabled:
            logger.info("В документе нет текстового слоя, но OCR отключен в настройках.")
            return [{"type": "text", "value": "В документе нет текстового слоя (скан). Включите OCR в настройках."}]

        logger.info(f"Документ определен как скан. Запуск OCR движка: {ocr_engine}...")
        ocr_content = []

        try:
            doc = fitz.open(self.file_path)
            for page_idx, page in enumerate(doc):
                # Рендерим страницу в высоком разрешении (DPI ~ 200) для четкого распознавания
                pix = page.get_pixmap(dpi=200)
                img = Image.open(io.BytesIO(pix.tobytes("png")))

                # Запуск выбранного OCR движка
                boxes = OCRService.recognize_image(img, engine=ocr_engine, lang=ocr_lang)
                if not boxes:
                    continue

                # Реконструируем таблицу из распознанных боксов
                table_grid = OCRService.reconstruct_table_from_ocr(boxes)
                if table_grid and len(table_grid) >= 2 and any(len(row) >= 2 for row in table_grid):
                    ocr_content.append({
                        "type": "table",
                        "value": table_grid
                    })
                else:
                    # Если структура не табличная — сохраняем сплошным текстом
                    full_text = "\n".join(b["text"] for b in boxes)
                    if full_text.strip():
                        ocr_content.append({
                            "type": "text",
                            "value": f"--- Скан страницы {page_idx + 1} ---\n{full_text.strip()}"
                        })

        except Exception as e:
            logger.error(f"Ошибка при выполнении OCR над PDF: {e}")
            return [{"type": "text", "value": f"Ошибка OCR распознавания скана: {e}"}]

        return ocr_content if ocr_content else [{"type": "text", "value": "Не удалось распознать текст на скане"}]
