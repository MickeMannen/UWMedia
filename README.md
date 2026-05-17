# UWMedia (Underwater Media Processor)

UWMedia is a comprehensive tool for processing underwater videos and photos. It bridges the gap between your dive computer and your camera by matching dive logs (UDDF/FIT) to your media files, applying advanced color correction, and overlaying real-time telemetry.

## Key Features

- **Batch Processing**: Process entire directories of videos and photos in one command.
- **Advanced Color Correction**: Intelligent underwater color restoration based on frame-by-frame analysis.
- **Telemetry Overlay (HUD)**: Synchronize dive logs from Garmin (.FIT) and Shearwater (.UDDF) to create dynamic telemetry overlays.
- **Video Stabilization**: Multi-level 1-pass stabilization using FFmpeg's `deshake` filter (Low, Mid, High), High takes forever! (Dont recomment it)
- **Metadata Integrity**: Preserves original camera metadata (QuickTime, DJI, Sony) and injects correct timezone/location information.
- **Dynamic Naming**: Automatically rename files based on the "Date Taken" metadata (`YYYYMMDD_HHMMSS`).
- **HUD Packaging**: Support for portable HUD designs via `.zip` packages containing layouts and skins.
- **Log-to-Video Generation**: Create HEVC telemetry-only videos directly from dive logs on a black background.
- **FCPXML Support**: Automatically generates `.xml` files for rendered telemetry videos for instant import into Final Cut Pro.
- **Layout Validation**: Automatic verification of HUD layouts against loaded dive logs to prevent errors during processing.

## Installation

### System Requirements
1. **Python 3.10+**
2. **FFmpeg**: Must be in your system PATH.
3. **ExifTool**: Must be in your system PATH.

### Setup
```bash
# Clone the repository
git clone https://github.com/yourusername/UWMedia.git
cd UWMedia

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Command Line Interface (CLI)

The CLI is the primary way to process media batches.

```bash
# Basic color correction and stabilization
python main.py ./raw_videos/ ./output/ --color --stabilize

# Complete processing with dive logs and telemetry overlay
python main.py ./raw/ ./out/ --logs ./dive_logs/ --layout skins/perdix.zip --color

# Generate telemetry video directly from a log file
python main.py --render-log dive_log.fit --layout perdix_layout.json
```

#### Key Arguments:
- `--color`: Apply underwater color correction.
- `--stabilize [low|mid|high]`: Apply stabilization. `high` is optimized for 4K.
- `--logs <dir>`: Path to directory containing `.uddf` or `.fit` logs.
- `--layout <zip|json>`: Use a ZIP package or JSON layout for telemetry overlay. Automatically enables overlay.
- `--render-log <file>`: Create a telemetry-only HEVC video from a specific dive log (requires `--layout`).
- `--filename-format <template>`: Custom naming (e.g., `"%Y%m%d_%H%M%S_Bali"`).
- `--debug`: Show verbose FFmpeg output for troubleshooting.


### Graphical User Interface (GUI)

Launch the interactive HUD designer and preview tool:

```bash
python gui_main.py
```

## Technical Highlights

### Color Correction Algorithm
The color correction engine is an implementation of the logic found in [bornfree/dive-color-corrector](https://github.com/bornfree/dive-color-corrector). It performs a sophisticated analysis of red channel attenuation and applies non-linear gain and hue shifting to restore natural underwater tones.

### Metadata Handling
Powered by **PyExifTool**, UWMedia ensures that your processed files are not "blank" videos. It copies all vendor-specific tags and correctly handles the complex timezone offsets found in DJI, Sony, and GoPro files.

### High-Resolution Stabilization
Optimized for 4K footage, the stabilization system uses an expanded search range and mirrored edge handling to provide a professional look without the common "black border" effect.

### Layout Validation
To ensure reliability during batch processing, UWMedia validates HUD layouts against the actual dive telemetry before starting the render. It checks for:
- **Field Existence**: Verifies that requested telemetry fields (depth, temp, etc.) exist in the data model.
- **Tank Serial Matching**: Alerts users if the layout expects tank data (e.g., from a Garmin transmitter) that isn't present in the provided log files.
- **JSON Integrity**: Ensures layouts are correctly formatted and skin assets are accessible.

## License

[MIT License](LICENSE)

## Credits
- Color Algorithm: [bornfree](https://github.com/bornfree)
- Metadata: [ExifTool by Phil Harvey](https://exiftool.org/)
- Processing: [FFmpeg](https://ffmpeg.org/)
