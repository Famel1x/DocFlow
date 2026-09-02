"""Pydantic-модели для запросов и ответов API."""

from typing import Any, Optional
from pydantic import BaseModel


class ContentItem(BaseModel):
    """Элемент контента: текст или таблица."""
    type: str  # "text" | "table"
    value: Any  # str для текста, list[list[str]] для таблицы
    merges: Optional[list[dict[str, Any]]] = None


class ParsedFile(BaseModel):
    """Распарсенный файл с контентом."""
    file_id: str
    filename: str
    file_type: str
    tables: list[Any]  # Список таблиц (dict c value/merges или list[list[str]])
    text_blocks: list[str]  # Текстовые блоки
    content: list[ContentItem]  # Полный контент в порядке появления


class TransformRequest(BaseModel):
    """Запрос на преобразование таблицы по правилам."""
    file_id: str
    table_index: int
    rules: str  # Текстовые правила от пользователя


class UpdateTableRequest(BaseModel):
    """Запрос на обновление отредактированной таблицы."""
    file_id: str
    table_index: int
    table: list[list[str]]
    merges: list[dict[str, int]] = []



class SaveConvertedTableRequest(BaseModel):
    """Запрос на фиксацию преобразованного текста для таблицы."""
    file_id: str
    table_index: int
    converted_text: str


class GenerateRequest(BaseModel):
    """Запрос на генерацию текста через GigaChat."""
    text: str  # Текст для отправки в LLM
    system_prompt: str = ""  # Системный промпт


class GigaChatSettings(BaseModel):
    """Настройки GigaChat API."""
    auth_mode: str = "key"  # "key" (Basic Auth) или "cert" (Сертификаты Минцифры/Клиентские)
    auth_key: str = ""  # Authorization key для получения токена (в режиме key)
    cert_file: str = ""  # Путь к файлу сертификата (cert.crt / client.pem)
    key_file: str = ""  # Путь к приватному ключу (key.pem)
    ca_file: str = ""  # Путь к доверенному корневому сертификату (Russian Trusted Root CA)
    scope: str = "GIGACHAT_API_PERS"  # GIGACHAT_API_PERS, GIGACHAT_API_B2B, GIGACHAT_API_CORP
    model: str = "GigaChat"  # GigaChat, GigaChat-Plus, GigaChat-Pro
    temperature: float = 0.7
    # Настройки распознавания сканов (OCR)
    ocr_enabled: bool = True  # Распознавать сканы автоматически
    ocr_engine: str = "rapidocr"  # "rapidocr" (ONNX, быстрый) или "tesseract" (системный)
    ocr_lang: str = "rus+eng"  # Языки распознавания
    system_prompt: str = (
        "Ты — помощник для создания FAQ. "
        "Преобразуй предоставленные данные из таблицы в читаемый текст "
        "в формате вопрос-ответ. Сохраняй всю информацию, ничего не пропускай."
    )



class GenerateResponse(BaseModel):
    """Ответ от GigaChat."""
    result: str
    error: str = ""
