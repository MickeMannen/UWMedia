import pytest
from datetime import datetime
from pathlib import Path

from conftest import PHOTO, run_cli
from metadata.exif import MetadataHandler


class TestMetadata:

    def test_dji_timezone_calculation(self):
        from utils.tag_editor import calculate_dji_datetimes

        file_path = Path("DJI_20260502110658_0002_D_A001.MP4")
        mock_tags = {
            "QuickTime:OriginalFilePath": "/mnt/media_rw/sd/DCIM/DJI_001/DJI_20260502100659_0002_D_A001.MP4",
            "QuickTime:CreateDate": "2026:05:02 03:06:59",
            "CreateDate": "2026:05:02 03:06:59"
        }

        calculated = calculate_dji_datetimes(file_path, mock_tags)
        assert calculated is not None
        assert calculated["QuickTime:CreationDate"] == "2026:05:02 10:06:59+07:00"
        assert calculated["QuickTime:CreateDate"] == "2026:05:02 03:06:59"
        assert calculated["EXIF:DateTimeOriginal"] == "2026:05:02 10:06:59"
        assert calculated["EXIF:CreateDate"] == "2026:05:02 10:06:59"

    def test_batch_timezone_setting(self, tmp_path):
        import shutil
        from utils.tag_editor import apply_batch_timezone_to_file

        # Copy a test photo to tmp_path
        src_photo = PHOTO
        dest_photo = tmp_path / "test_photo.jpg"
        shutil.copy2(src_photo, dest_photo)

        meta = MetadataHandler()
        tz = meta._parse_timezone("-05:00")
        assert tz is not None

        updated = apply_batch_timezone_to_file(
            meta, dest_photo, "Keep local time, set offset", tz, "-05:00"
        )
        assert updated is True

        # Verify metadata is updated with the new offset
        tags = meta.get_tags(dest_photo, ["EXIF:OffsetTimeOriginal", "EXIF:OffsetTimeDigitized", "EXIF:OffsetTime"])
        assert tags.get("EXIF:OffsetTimeOriginal") == "-05:00"
        assert tags.get("EXIF:OffsetTime") == "-05:00"

    def test_metadata_viewer_filter(self):
        from utils.tag_editor import filter_metadata_rows

        mock_metadata = {
            "EXIF:DateTimeOriginal": "2026:05:21 06:58:22",
            "EXIF:Make": "Sony",
            "EXIF:Model": "ILCE-6700",
            "QuickTime:CreateDate": "2026:05:20 22:58:22"
        }
        rows = [{"tag": k, "value": str(v)} for k, v in mock_metadata.items()]
        assert len(rows) == 4

        # Filter for "Sony"
        visible = filter_metadata_rows(rows, "Sony")
        assert len(visible) == 1

        # Empty filter shows everything again
        visible = filter_metadata_rows(rows, "")
        assert len(visible) == 4

    @pytest.mark.render
    def test_cli_no_overwrite_and_move_original(self, tmp_path):
        import shutil
        
        src_photo = PHOTO
        
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
        
        cmd = [temp_src, out_dir, "--color", "--filename-format", "%Y%m%d_%H%M%S"]
        result = run_cli(*cmd)
        assert result.returncode == 0, result.stderr
        assert expected_output.exists()
        
        # Modify the output file content slightly so we can detect if it got overwritten
        with open(expected_output, "w") as f:
            f.write("mock_content")
            
        # 3. Run second time with --no-overwrite: should skip because target exists
        cmd_no_overwrite = cmd + ["--no-overwrite"]
        result = run_cli(*cmd_no_overwrite)
        assert result.returncode == 0, result.stderr
        
        # Verify it skipped (the file should still have our mocked content instead of being overwritten with a real image)
        with open(expected_output, "r") as f:
            content = f.read()
        assert content == "mock_content"
        
        # 4. Run third time with --move-original: should process (if we delete the output file or use a different output name)
        # and then move the original file to move_dir
        expected_output.unlink() # delete the target so it processes
        
        cmd_move = cmd + ["--move-original", move_dir]
        result = run_cli(*cmd_move)
        assert result.returncode == 0, result.stderr
        
        # Verify the original source has been moved to move_dir
        expected_moved_src = move_dir / "DSC03491.JPG"
        assert expected_moved_src.exists()
        assert not temp_src.exists()

    @pytest.mark.render
    def test_jpeg_quality_and_subsampling(self, tmp_path):
        import shutil
        from PIL import Image, JpegImagePlugin

        src_photo = PHOTO
        
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
        cmd = [temp_src, out_dir, "--color", "--filename-format", "%Y%m%d_%H%M%S"]
        result = run_cli(*cmd)
        assert result.returncode == 0, result.stderr
        
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

    @pytest.mark.render
    def test_summary_output(self, tmp_path):
        import shutil

        src_photo = PHOTO
        
        # Setup temp source and output dirs
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        
        temp_src = src_dir / "DSC03491.JPG"
        shutil.copy2(src_photo, temp_src)
        
        # Run cli_main.py with --color and --summary
        cmd = [temp_src, out_dir, "--color", "--summary"]
        result = run_cli(*cmd)
        assert result.returncode == 0, result.stderr
        
        # Verify output exists
        expected_output = out_dir / "20251203_091548_980.jpg"
        assert expected_output.exists()
        
        # Verify summary section exists in output
        assert "UWMedia Activity Summary" in result.stdout
        assert "Reading Photo" in result.stdout
        assert "Color Correction" in result.stdout
        assert "Saving Photo" in result.stdout
        assert "Metadata Copying" in result.stdout





