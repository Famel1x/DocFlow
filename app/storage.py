"""In-memory хранилище для загруженных файлов с персистентным сохранением настроек в JSON."""

import json
import os
import sys
import logging
from typing import Any
from app.models import GigaChatSettings

logger = logging.getLogger(__name__)

if getattr(sys, "frozen", False):
    EXE_DIR = os.path.dirname(sys.executable)
    SETTINGS_FILE = os.path.join(EXE_DIR, "settings.json")
else:
    SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")



class Storage:
    """Хранилище в памяти с сохранением настроек на диск."""

    def __init__(self):
        self.files: dict[str, dict[str, Any]] = {}
        self.settings = self._load_settings()

    def _load_settings(self) -> GigaChatSettings:
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return GigaChatSettings(**data)
            except Exception as e:
                logger.error(f"Не удалось загрузить настройки из {SETTINGS_FILE}: {e}")
        return GigaChatSettings()

    def _save_settings(self) -> None:
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings.model_dump(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Не удалось сохранить настройки в {SETTINGS_FILE}: {e}")

    def add_file(self, file_id: str, data: dict[str, Any]) -> None:
        self.files[file_id] = data

    def get_file(self, file_id: str) -> dict[str, Any] | None:
        return self.files.get(file_id)

    def get_all_files(self) -> dict[str, dict[str, Any]]:
        return self.files

    def remove_file(self, file_id: str) -> None:
        self.files.pop(file_id, None)

    def clear_files(self) -> None:
        self.files.clear()

    def update_settings(self, settings: GigaChatSettings) -> None:
        self.settings = settings
        self._save_settings()

    def get_settings(self) -> GigaChatSettings:
        return self.settings


# Глобальный экземпляр хранилища
storage = Storage()
