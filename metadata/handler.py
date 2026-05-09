import subprocess
import json
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

class MetadataHandler:
    def __init__(self):
        pass

    def get_video_metadata(self, file_path: str) -> dict:
        """Extract metadata using ExifTool."""
        cmd = [
            "exiftool",
            "-j",
            "-QuickTime:CreateDate",
            "-QuickTime:Timezone",
            "-QuickTime:FileLocation",
            "-GPSPosition",
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ExifTool failed: {result.stderr}")
        
        return json.loads(result.stdout)[0]

    def get_standardized_creation_date(self, file_path: str) -> datetime:
        meta = self.get_video_metadata(file_path)
        
        create_date_str = meta.get("CreateDate")
        if not create_date_str:
            raise ValueError("No CreateDate found in video metadata")
            
        # Standard format: 2023:10:27 12:34:56
        create_date = datetime.strptime(create_date_str, "%Y:%m:%d %H:%M:%S")
        
        # Sony style: Timezone is explicit
        tz_str = meta.get("Timezone")
        if tz_str:
            # Handle formats like +02:00 or 02:00
            match = re.match(r"([+-])?(\d{2}):(\d{2})", tz_str)
            if match:
                sign, hh, mm = match.groups()
                offset = timedelta(hours=int(hh), minutes=int(mm))
                if sign == "-":
                    offset = -offset
                return create_date.replace(tzinfo=timezone(offset))

        # DJI style: Infer from GPS if available
        gps = meta.get("FileLocation") or meta.get("GPSPosition")
        if gps:
            # Simplification: In a real app we'd use a timezone-by-coords library
            # For now, we assume CreateDate is local if timezone is missing
            # and we just return it as naive or assume UTC if that's camera default
            pass
            
        # Default: Assume local time (naive) as per DJI requirement
        return create_date
