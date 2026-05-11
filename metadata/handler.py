import subprocess
import json
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

class MetadataHandler:
    def __init__(self):
        pass

    def get_video_metadata(self, file_path: Path) -> dict:
        """Extract metadata using ExifTool."""
        cmd = [
            "exiftool",
            "-j",
            "-QuickTime:CreateDate",
            "-QuickTime:CreationDate",
            "-QuickTime:Timezone",
            "-QuickTime:TimeZone",
            "-QuickTime:FileLocation",
            "-GPSPosition",
            str(file_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ExifTool failed: {result.stderr}")
        
        return json.loads(result.stdout)[0]

    def _parse_timezone(self, tz_str: str) -> Optional[timezone]:
        if not tz_str:
            return None
        # Support formats like +02:00, 02:00, or +0200
        match = re.match(r"([+-])?(\d{2}):?(\d{2})", tz_str)
        if match:
            sign, hh, mm = match.groups()
            offset = timedelta(hours=int(hh), minutes=int(mm))
            if sign == "-":
                offset = -offset
            return timezone(offset)
        return None

    def get_standardized_creation_date(self, file_path: Path) -> datetime:
        """Returns the creation date in UTC (aware)."""
        meta = self.get_video_metadata(file_path)
        
        # 1. Try CreationDate (often contains offset)
        creation_str = meta.get("CreationDate")
        if creation_str:
            try:
                # 2023:10:27 12:34:56+08:00
                dt = datetime.strptime(creation_str[:19], "%Y:%m:%d %H:%M:%S")
                tz = self._parse_timezone(creation_str[19:])
                if tz:
                    return dt.replace(tzinfo=tz).astimezone(timezone.utc)
            except:
                pass

        # 2. Try CreateDate (usually UTC in QuickTime)
        create_str = meta.get("CreateDate")
        if create_str:
            dt = datetime.strptime(create_str, "%Y:%m:%d %H:%M:%S")
            return dt.replace(tzinfo=timezone.utc)

        raise ValueError("No valid creation date found in video metadata")

    def get_local_creation_date(self, file_path: Path) -> datetime:
        """Returns the creation date in Local time (naive)."""
        meta = self.get_video_metadata(file_path)
        
        # 1. Try CreationDate directly
        creation_str = meta.get("CreationDate")
        if creation_str:
            try:
                return datetime.strptime(creation_str[:19], "%Y:%m:%d %H:%M:%S")
            except:
                pass

        # 2. Try CreateDate + Timezone/TimeZone
        create_str = meta.get("CreateDate")
        if create_str:
            utc_dt = datetime.strptime(create_str, "%Y:%m:%d %H:%M:%S").replace(tzinfo=timezone.utc)
            # Check both 'Timezone' and 'TimeZone' (Sony style)
            tz_str = meta.get("Timezone") or meta.get("TimeZone")
            tz = self._parse_timezone(tz_str)
            if tz:
                local_dt = utc_dt.astimezone(tz)
                return local_dt.replace(tzinfo=None)
            
            return utc_dt.replace(tzinfo=None)

        raise ValueError("No valid creation date found in video metadata")
