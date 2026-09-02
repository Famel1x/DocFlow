from abc import ABC, abstractmethod
from typing import List, Dict, Any

class BaseParser(ABC):
    """Базовый класс для всех парсеров документов."""
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        
    @abstractmethod
    def parse(self) -> List[Dict[str, Any]]:
        """
        Парсит документ и возвращает список элементов (текст или таблица)
        с сохранением порядка.
        """
        pass
