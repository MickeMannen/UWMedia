import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from exiftool import ExifTool, ExifToolHelper

date_time_formats = [(re.compile(r'^(?P<date>\d+:\d+:\d+) (?P<time>\d+:\d+:\d+.\d+)(?P<zone>[+-]\d+:\d+)$'),
                      "%Y:%m:%d %H:%M:%S.%f%z"),

                     (re.compile(r'^(?P<date>\d+:\d+:\d+) (?P<time>\d+:\d+:\d+)$'), "%Y:%m:%d %H:%M:%S"),
                    (re.compile(r'^(?P<date>\d+:\d+:\d+) (?P<time>\d+:\d+:\d+)(?P<zone>[+-]\d+:\d+)$'),
                     "%Y:%m:%d %H:%M:%S%z"),
                     (re.compile(r'^(?P<date>\d+-\d+-\d+) (?P<time>\d+:\d+:\d+)$'), "%Y-%m-%d %H:%M:%S"),
                        (re.compile(r'^(?P<date>\d+-\d+-\d+) (?P<time>\d+:\d+:\d+)(?P<zone>[+-]\d+:\d+)$'),
                     "%Y-%m-%d %H:%M:%S%z"),
                     (re.compile(r'^(?P<date>\d+-\d+-\d+)T(?P<time>\d+:\d+:\d+)(?P<zone>[+-]\d+:\d+)$'),
                      "%Y-%m-%dT%H:%M:%S%z"),
                        (re.compile(r'^(?P<date>\d+-\d+-\d+)T(?P<time>\d+:\d+:\d+)Z$'),
                        "%Y-%m-%dT%H:%M:%SZ")
                     ]

class MetadataHandler:
    def __init__(self):
        pass

    def copy_all(self, src: Path, dest: Path):
        """Copies all metadata from source to target."""

        with ExifTool() as et:
            et.execute(b"-TagsFromFile", str(src).encode('utf-8'),
                       b"-all:all", b"-overwrite_original", str(dest).encode('utf-8'))

        tz_offset_mins = self.get_timezone_offset(src)
        # 7. Apply Timezone Tags if missing/calculated
        if tz_offset_mins is not None:
            creation_date = self.get_local_creation_date(src)

            sign = "+" if tz_offset_mins >= 0 else "-"
            hours = abs(tz_offset_mins) // 60
            mins = abs(tz_offset_mins) % 60
            # ISO 8601 offset format for CreationDate: +HH:MM
            tz_iso = f"{sign}{hours:02}:{mins:02}"

            # Format: 2023:10:27 12:34:56+08:00
            creation_date_with_tz = creation_date.strftime("%Y:%m:%d %H:%M:%S") + tz_iso

            tags = {
                "QuickTime:CreationDate": creation_date_with_tz,
                "QuickTime:Timezone": tz_iso,
                "QuickTime:TimeZone": tz_iso  # Sony style
            }
            print(f"Injecting Timezone Tags: {tags}")
            self.set_quicktime_tags(dest, tags)

        # Set xmp date taken if not present
        meta = self.get_metadata(src)

        if not any(key.startswith("XML:") for key in meta):
            # meta = exif._get_metadata(Path(file))
            self.set_xmp_data(meta, dest)

            print("Set XMP data")

    def set_xmp_data(self, data, dest: Path):
        """
        exiftool "-XMP:CreateDate=2025-09-15T14:41:00+07:00" file.jpg

        :param data:
        :type data: dict
        :param dest:
        :return:
        """
        # "XML:LastUpdate": "2025:09:13 09:37:36+07:00",
        # "XML:VideoFormatVideoFrameCaptureFps": "50.00p",
        #   "XML:VideoFormatVideoFrameCaptureFps": "50p", xmpDM:videoFrameRate
        # "XML:DeviceManufacturer": "Sony", tiff:Make
        # "XML:DeviceModelName": "ILCE-6700", tiff:Model
        #   "XML:LensModelName": "E PZ 16-50mm F3.5-5.6 OSS", aux:Lens
        key_mapping = {"XML:LastUpdate":
                           {"tag": "xmp:MetadataDate", "ftype": datetime, "format": '%Y:%m:%d %H:%M:%S%z'},
                       "XML:CreationDateValue":
                           {"tag": "xmp:CreateDate", "ftype": datetime, "format": '%Y:%m:%d %H:%M:%S%z'},
                       "XML:VideoFormatVideoFrameCaptureFps":
                           {"tag": "XMP-xmpDM:videoFrameRate", "ftype": str, "regex": r'p$'},
                       "XML:DeviceManufacturer":
                           {"tag": "XMP:Make", "ftype": str},
                       "XML:DeviceModelName":
                           {"tag": "XMP:Model", "ftype": str},
                       "XML:LensModelName":
                           {"tag": "XMP-aux:lens", "ftype": str,},
                       }

        cmd = []
        for key, value in data.items():
            if key in key_mapping:
                tag_info = key_mapping[key]
                tag = tag_info["tag"]
                ftype = tag_info["ftype"]
                if isinstance(value, str) and ftype == str:
                    # str case
                    if tag_info.get('regex', None) is not None:
                        value = re.sub(tag_info.get('regex', ''), '', value)
                    cmd.append(f"-{tag}={value}".encode('utf-8'))
                elif (isinstance(value, datetime) or self._date_str_to_datetime(value) is not None) and ftype == datetime:
                    # datetime case
                    t_value = self._date_str_to_datetime(value)
                    date_str = t_value.strftime(tag_info.get("format"))
                    if tag_info.get("format") == '%Y:%m:%d %H:%M:%S%z':
                        date_str = date_str[:-2] + ':' + date_str[-2:]
                    cmd.append(f"-{tag}={date_str}".encode('utf-8'))

        if len(cmd) > 0:
            cmd.append(b"-overwrite_original")
            cmd.append(str(dest).encode('utf-8'))
            # print(cmd)
            with ExifTool() as et:
                status = et.execute(*cmd)
                print(et.last_stderr)
        else:
            print("No XMP data to write")

    def _date_str_to_datetime(self, date_str:str)->Optional[datetime]:
        try:
            for d_reg, d_format in date_time_formats:
                if d_reg.match(date_str):
                    return datetime.strptime(date_str, d_format)
        except ValueError as e:
            print(f"Error parsing DateTimeOriginal: {e}")
        return None

    def set_quicktime_tags(self, src: Path, tags: Dict[str, Any]):
        """
        Write tags to a file using ExifTool.execute.
        Returns a tuple (stdout_bytes, stderr_str).
        """
        cmd = []
        for tag, value in tags.items():
            # Format datetime values like 'YYYY:MM:DD HH:MM:SS+HH:MM'
            if isinstance(value, datetime):
                date_str = value.strftime('%Y:%m:%d %H:%M:%S%z')
                if len(date_str) >= 5:
                    # Insert colon into timezone offset if missing (e.g. +0800 -> +08:00)
                    if ':' not in date_str[-5:]:
                        date_str = date_str[:-2] + ':' + date_str[-2:]
                value_str = date_str
            else:
                value_str = str(value)
            cmd.append(f"-{tag}={value_str}".encode('utf-8'))

        cmd.append(b"-overwrite_original")
        cmd.append(str(src).encode('utf-8'))

        with ExifTool() as et:
            stdout = et.execute(*cmd)
            stderr = et.last_stderr
        return stdout, stderr

    def get_metadata(self, src: Path) -> Optional[dict]:
        """Extracts all metadata using ExifToolHelper."""
        try:
            with ExifToolHelper() as et:
                metadata = et.get_metadata(str(src))
                return metadata[0]
        except Exception as e:
            print(f"Error parsing metadata: {e}")
            return None

    def _parse_timezone(self, tz_str: Any) -> Optional[timezone]:
        if not tz_str:
            return None
        # Convert to string if it's an int/float (minutes offset)
        if isinstance(tz_str, (int, float)):
            offset = timedelta(minutes=int(tz_str))
            return timezone(offset)
            
        tz_str = str(tz_str)
        # Support formats like +02:00, 02:00, or +0200
        match = re.match(r"([+-])?(\d{2}):?(\d{2})", tz_str)
        if match:
            sign, hh, mm = match.groups()
            offset = timedelta(hours=int(hh), minutes=int(mm))
            if sign == "-":
                offset = -offset
            return timezone(offset)
        return None

    def get_timezone_offset(self, file_path: Path) -> Optional[int]:
        """Calculates timezone offset in minutes by comparing CreateDate (UTC) and CreationDate (Local)."""
        meta = self.get_metadata(file_path)
        if not meta:
            return None
        
        create_str = meta.get("QuickTime:CreateDate") or meta.get("CreateDate")
        creation_str = meta.get("QuickTime:CreationDate") or meta.get("CreationDate")
        
        if create_str and creation_str:
            try:
                create_str = str(create_str)
                creation_str = str(creation_str)
                # CreationDate might already have an offset, check that first
                match = re.search(r"([+-]\d{2}:?\d{2})$", creation_str)
                if match:
                    tz = self._parse_timezone(match.group(1))
                    if tz:
                        return int(tz.utcoffset(None).total_seconds() / 60)

                # Otherwise calculate from difference
                utc_dt = datetime.strptime(create_str[:19], "%Y:%m:%d %H:%M:%S")
                local_dt = datetime.strptime(creation_str[:19], "%Y:%m:%d %H:%M:%S")
                
                # Difference in minutes
                offset_mins = int((local_dt - utc_dt).total_seconds() / 60)
                # Round to nearest 15 mins to avoid slight clock drift issues
                return round(offset_mins / 15) * 15
            except:
                pass
        
        # Fallback to Sony style Timezone/TimeZone tags
        tz_val = meta.get("QuickTime:Timezone") or meta.get("QuickTime:TimeZone") or \
                 meta.get("Timezone") or meta.get("TimeZone")
        if tz_val is not None:
            tz = self._parse_timezone(tz_val)
            if tz:
                return int(tz.utcoffset(None).total_seconds() / 60)

        return None

    def get_standardized_creation_date(self, file_path: Path) -> datetime:
        """Returns the creation date in UTC (aware)."""
        meta = self.get_metadata(file_path)
        if not meta:
            raise ValueError("Could not extract metadata")
        
        # 1. Try CreationDate (often contains offset)
        creation_str = meta.get("QuickTime:CreationDate") or meta.get("CreationDate")
        if creation_str:
            try:
                creation_str = str(creation_str)
                # 2023:10:27 12:34:56+08:00
                dt = datetime.strptime(creation_str[:19], "%Y:%m:%d %H:%M:%S")
                tz = self._parse_timezone(creation_str[19:])
                if tz:
                    return dt.replace(tzinfo=tz).astimezone(timezone.utc)
            except:
                pass

        # 2. Try CreateDate (usually UTC in QuickTime)
        create_str = meta.get("QuickTime:CreateDate") or meta.get("CreateDate")
        if create_str:
            create_str = str(create_str)
            dt = datetime.strptime(create_str[:19], "%Y:%m:%d %H:%M:%S")
            return dt.replace(tzinfo=timezone.utc)

        raise ValueError("No valid creation date found in video metadata")

    def get_local_creation_date(self, file_path: Path) -> datetime:
        """Returns the creation date in Local time (naive). Works for videos and photos."""
        meta = self.get_metadata(file_path)
        if not meta:
            raise ValueError("Could not extract metadata")
        
        # 1. Try common video tags
        creation_str = meta.get("QuickTime:CreationDate") or meta.get("CreationDate") or \
                       meta.get("EXIF:DateTimeOriginal") or meta.get("DateTimeOriginal") or \
                       meta.get("EXIF:CreateDate")
        
        if creation_str:
            try:
                creation_str = str(creation_str)
                # Handle formats like '2023:10:27 12:34:56' or with offset
                return datetime.strptime(creation_str[:19], "%Y:%m:%d %H:%M:%S")
            except:
                pass

        # 2. Try CreateDate + Timezone/TimeZone
        create_str = meta.get("QuickTime:CreateDate") or meta.get("CreateDate")
        if create_str:
            create_str = str(create_str)
            utc_dt = datetime.strptime(create_str[:19], "%Y:%m:%d %H:%M:%S").replace(tzinfo=timezone.utc)
            # Check both 'Timezone' and 'TimeZone' (Sony style)
            tz_val = meta.get("QuickTime:Timezone") or meta.get("QuickTime:TimeZone") or \
                     meta.get("Timezone") or meta.get("TimeZone")
            tz = self._parse_timezone(tz_val)
            if tz:
                local_dt = utc_dt.astimezone(tz)
                return local_dt.replace(tzinfo=None)
            
            return utc_dt.replace(tzinfo=None)

        raise ValueError("No valid creation date found in video metadata")
