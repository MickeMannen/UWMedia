from abc import ABC, abstractmethod
from typing import List
from datetime import datetime
from pathlib import Path
from models.dive import Dive

class BaseParser(ABC):
    @abstractmethod
    def parse(self, file_path: Path) -> List[Dive]:
        pass
