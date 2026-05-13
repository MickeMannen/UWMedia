import pytest
from datetime import datetime
from pathlib import Path

from metadata.exif import MetadataHandler


class TestMetadata:

    def test_datetaken(self):
        # Use relative path for better portability
        path = Path("test_data/videos_original")
        meta = MetadataHandler()
        
        files = list(path.glob("*.[mM][pP]4"))
        print(f"\nDEBUG: Found {len(files)} files in {path}")
        
        for file in files:
            try:
                if file.name == "20251019_M0281.MP4":
                    pass
                print(f"DEBUG: Processing {file.name}...")
                utc_time = meta.get_standardized_creation_date(file_path=file)
                local_time = meta.get_local_creation_date(file_path=file)
                print(f"RESULT: {file.name} -> UTC: {utc_time} | Local: {local_time}")
            except Exception as e:
                print(f"ERROR: {file.name} -> {e}")

