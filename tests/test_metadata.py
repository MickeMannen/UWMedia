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

    def test_debug_datetaken(self):
        # Use relative path for better portability
        file = Path("/Users/mikael/development/UWMedia/test_data/videos_corrected/test01.mp4")
        # file = Path("/Users/mikael/development/UWMedia/test_data/videos_corrected/20251019_M0281_color.MP4")
        file = Path("/Users/mikael/development/UWMedia/test_data/videos_corrected/20251019_102131_1.mp4")
        file = Path("/Users/mikael/DivingMedia/20260501_Phuket/videos_original/DJI_20260502110658_0002_D_A001.MP4")
        file = Path("/Users/mikael/development/UWMedia/test_data/videos_wrong_tz/DJI_20260502110658_0002_D_A001_correct_tz.mp4")
        file = Path("/Users/mikael/DivingMedia/20260501_Phuket/videos_original_corrected/DJI_20260503123846_0017_D_A001.mp4")
        file = Path("/Users/mikael/DivingMedia/20260524_Sipadan/original_photo/DSC06413.JPG")

        meta = MetadataHandler()


        try:
            metadata = meta.get_metadata(src=file)
            print(f"DEBUG: Processing {file.name}...")
            utc_time = meta.get_standardized_creation_date(file_path=file)
            local_time = meta.get_local_creation_date(file_path=file)
            print(f"RESULT: {file.name} -> UTC: {utc_time} | Local: {local_time}")
        except Exception as e:
            print(f"ERROR: {file.name} -> {e}")

    def test_dji_timezone_calculation(self):
        from tag_editor_main import TagEditorApp
        from PySide6.QtWidgets import QApplication
        import sys
        
        # We need a QApplication instance to create/test PySide6 widgets
        app = QApplication.instance()
        if not app:
            app = QApplication(sys.argv)
            
        editor = TagEditorApp()
        
        # Test case: mock tags
        file_path = Path("DJI_20260502110658_0002_D_A001.MP4")
        mock_tags = {
            "QuickTime:OriginalFilePath": "/mnt/media_rw/sd/DCIM/DJI_001/DJI_20260502100659_0002_D_A001.MP4",
            "QuickTime:CreateDate": "2026:05:02 03:06:59",
            "CreateDate": "2026:05:02 03:06:59"
        }
        
        calculated = editor.calculate_dji_datetimes(file_path, mock_tags)
        assert calculated is not None
        assert calculated["QuickTime:CreationDate"] == "2026:05:02 10:06:59+07:00"
        assert calculated["QuickTime:CreateDate"] == "2026:05:02 03:06:59"
        assert calculated["EXIF:DateTimeOriginal"] == "2026:05:02 10:06:59"
        assert calculated["EXIF:CreateDate"] == "2026:05:02 10:06:59"

    def test_cli_no_overwrite_and_move_original(self, tmp_path):
        import subprocess
        import shutil
        
        src_photo = Path("test_data/release_test/DSC03491.JPG")
        
        # 1. Setup temp source and output dirs
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        move_dir = tmp_path / "move"
        move_dir.mkdir()
        
        temp_src = src_dir / "DSC03491.JPG"
        shutil.copy2(src_photo, temp_src)
        
        # 2. Run first time: should process and output the file with milliseconds
        expected_output = out_dir / "20251203_091548_980.jpg"
        
        cmd = [
            "python3", "cli_main.py", str(temp_src), str(out_dir),
            "--color", "--filename-format", "%Y%m%d_%H%M%S"
        ]
        subprocess.run(cmd, check=True)
        assert expected_output.exists()
        
        # Modify the output file content slightly so we can detect if it got overwritten
        with open(expected_output, "w") as f:
            f.write("mock_content")
            
        # 3. Run second time with --no-overwrite: should skip because target exists
        cmd_no_overwrite = cmd + ["--no-overwrite"]
        subprocess.run(cmd_no_overwrite, check=True)
        
        # Verify it skipped (the file should still have our mocked content instead of being overwritten with a real image)
        with open(expected_output, "r") as f:
            content = f.read()
        assert content == "mock_content"
        
        # 4. Run third time with --move-original: should process (if we delete the output file or use a different output name)
        # and then move the original file to move_dir
        expected_output.unlink() # delete the target so it processes
        
        cmd_move = cmd + ["--move-original", str(move_dir)]
        subprocess.run(cmd_move, check=True)
        
        # Verify the original source has been moved to move_dir
        expected_moved_src = move_dir / "DSC03491.JPG"
        assert expected_moved_src.exists()
        assert not temp_src.exists()

    def test_jpeg_quality_and_subsampling(self, tmp_path):
        import subprocess
        import shutil
        from PIL import Image, JpegImagePlugin

        src_photo = Path("test_data/release_test/DSC03491.JPG")
        
        # 1. Setup temp source and output dirs
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        
        temp_src = src_dir / "DSC03491.JPG"
        shutil.copy2(src_photo, temp_src)
        
        # 2. Get original subsampling
        with Image.open(src_photo) as img:
            original_subsampling = JpegImagePlugin.get_sampling(img)
        
        # 3. Run cli_main.py with --color
        cmd = [
            "python3", "cli_main.py", str(temp_src), str(out_dir),
            "--color", "--filename-format", "%Y%m%d_%H%M%S"
        ]
        subprocess.run(cmd, check=True)
        
        # 4. Verify output file exists
        expected_output = out_dir / "20251203_091548_980.jpg"
        assert expected_output.exists()
        
        # 5. Verify quality and subsampling match the original
        with Image.open(expected_output) as img:
            saved_subsampling = JpegImagePlugin.get_sampling(img)
            quantization = img.quantization
            
        assert saved_subsampling == original_subsampling
        
        # Check that quantization tables match the original ones
        with Image.open(src_photo) as orig:
            original_quantization = orig.quantization
        
        assert quantization == original_quantization




