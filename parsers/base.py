from abc import ABC, abstractmethod
from typing import List
from datetime import datetime
from models.dive import Dive

class BaseParser(ABC):
    @abstractmethod
    def parse(self, file_path: str) -> List[Dive]:
        pass
