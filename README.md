# UWMedia (Underwater Media Processor)

<p align="center">
  <a href="https://skillicons.dev">
    <img src="https://skillicons.dev/icons?i=python,bash,qt,git,md" alt="Tech Stack" />
  </a>
</p>

<p align="center">
      <img src="https://img.shields.io/badge/Google_Gemini-8E75C2?style=for-the-badge&logo=googlegemini&logoColor=white" alt="Gemini" />
      <img src="https://img.shields.io/badge/Claude_AI-D97756?style=for-the-badge&logo=claude&logoColor=white" alt="Claude" />
    </p>


UWMedia is a tool for processing underwater videos and photos. It can use telemetry information from dive computers to generate an overlay on photos and videos. There is also support for color correction so you don't have to do every photo / video one by one.

When i started the project 2025 I wanted the overlay data from the dive computer on my videos. At the same time I added a basic color correction but it wasn't very good.
Since then I started to use Gemini and Antigravity to be able to test alternative solutions and get a better color correction.

Example of Photo before and after

![DSC06641_side_by_side.jpg](media/DSC06641_side_by_side.jpg)

Photo with Telemetry data
![DSC06641_color_garmin_overlay.jpg](media/DSC06641_color_garmin_overlay.jpg)


## [Example (YouTube)](https://youtu.be/8r8_4H4iOMg)

## Key Features

- **Batch Processing**: Process entire directories of videos and photos in one command.
- **Fast 3D LUT Color Pipeline**: Dynamic 3D LUT (`.cube`) generation from profile settings, executing color correction natively in FFmpeg to bypass Python overhead and speed up vs processing frame by frame.
- **Advanced Color Correction**: Underwater color restoration with custom profiles (vivid, subtle, default) saved in `color.yaml`.
- **Telemetry Overlay (HUD)**: Synchronize dive logs from Garmin (.FIT), Subsurface (.XML), and Shearwater (.UDDF) to create dynamic telemetry overlays.
- **Batch Telemetry Overlays (`--render-video-log`)**: Automatically generate matching black-background overlay videos/photos for all raw files in a folder, preserving creation timestamps and duration.
- **Metadata Integrity**: Preserves original camera metadata (QuickTime, DJI, Sony) and injects correct timezone/location information.
- **Dynamic Naming**: Automatically rename files based on the "Date Taken" metadata (`YYYYMMDD_HHMMSS`).
- **HUD Packaging**: Support for portable HUD designs via `.zip` packages containing layouts and skins, the GUI application makes it possible to edit existing HUD or create your own.
- **Log-to-Video Generation**: Create HEVC telemetry-only videos directly from dive logs on a black background, with size automatically adjusted to layout dimensions.
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

Alternative if you want to use a binary (pyinstaller) - download from releases, make sure to use the latest overlays or edit your own overlay with new gui_main. Please note that it takes one minute for the Pyinstaller image to get started - Numpy has to be unpacked.

### Building Executables

If you want to package the applications into standalone binaries yourself, use the `build.sh` script. It automatically uses the project's virtual environment and builds all apps (CLI, GUI, and Tag Editor) using PyInstaller:

```bash
# Build all apps
./build.sh

# Or build a specific target
./build.sh --target cli

# Or specify a custom version/revision
./build.sh --revision 1.0.0
```

## Usage

### Command Line Interface (CLI)

The CLI is the primary way to process media batches.

```bash
# Basic color correction (utilizing the fast 3D LUT pipeline)
python cli_main.py ./raw_videos/ ./output/ --color

# Complete processing with dive logs and telemetry overlay
python cli_main.py ./raw/ ./out/ --logs ./dive_logs/ --layout skins/perdix.zip --color

# Generate telemetry video directly from a log file (size matches layout dimensions)
python cli_main.py --render-log dive_log.fit --layout perdix_layout.json

# Generate telemetry video directly from a log file, limiting to the first 100 waypoints (useful for testing)
python cli_main.py --render-log dive_log.fit 100 --layout perdix_layout.json

# Batch generate telemetry overlay files for all photos/videos in a folder (matched to log times)
python cli_main.py ./raw/ ./out/ --render-video-log --layout skins/perdix.zip --logs ./dive_logs/
```

#### Configuration files
- color.yaml
- hud_rules.json
- config.yaml

#### Key Arguments:
- `--color`: Apply underwater color correction. Takes one argument - color profile - if not added default is used.
- `--logs <dir>`: Path to directory containing `.uddf`, `.fit`, or subsurface `.xml` logs (Make sure you don't have duplicates).
- `--layout <zip|json>`: Use a ZIP package or JSON layout for telemetry overlay. Automatically enables overlay.
- `--render-log <file> [num_waypoints]`: Create a telemetry-only HEVC video from a specific dive log (requires `--layout`). You can optionally specify a second argument for the number of waypoints to render (e.g., `100`) to limit processing time during testing.
- `--filename-format <template>`: Custom naming (e.g., `"%Y%m%d_%H%M%S_Bali"`).
- `--render-video-log`: Generate a telemetry-only video based on files in input directory
- `--create-config`: Scan the log directory and generate a config file for TANK names
- `--debug`: Show verbose FFmpeg output for troubleshooting.


### Graphical User Interfaces (GUIs)

UWMedia includes two interactive GUI applications to design overlays and fine-tune correction profiles.

#### 1. HUD Designer & Sync (`gui_main.py`)

Launch the interactive HUD designer and preview tool:

```bash
python gui_main.py
```

- **Features**: Customizing and positioning telemetry fields, shapes, and background skins.
- **Dynamic Overlays**: Select custom widgets (such as the Depth Graph Overlay) from a dropdown list and click "Add" to overlay them onto the HUD canvas.

Please share if you make a fancy HUD!

HUD Example

![Garmin_Sidemount_image.png](media/Garmin_Sidemount_image.png)
![Shearwater_Perdix2.png](media/Shearwater_Perdix2.png)

#### 2. Color Tuning Tool (`color_tuning_gui.py`)

Launch the color correction profile editor and preview tool:

```bash
python color_tuning_gui.py
```

- **Side-by-Side Preview**: Compare the **Original** raw photo on the left with the corrected **Adjusted** photo on the right in real-time.
- **Precision Adjustments**: Sliders to tune restoration weights, white balance, exposure, OKLCh hue shifts, plus post-processing adjustments for **Sharpness** (using an unsharp mask) and **Darkness** offset.
- **Profile Management**: Save adjustments back to existing profiles or **Save as New Profile** directly to `color.yaml`.
- **Path Memory & Info**: Automatically remembers the folder location of your loaded photos across sessions and displays the absolute path of the original file in a bottom status bar.


## Technical Highlights

### 3D LUT Color Correction
For standalone video color correction, UWMedia generates a 3D Lookup Table (`.cube` file) dynamically from the parameter configurations in `color.yaml` and executes the color grading natively inside FFmpeg using the `lut3d` filter. This bypasses the Python interpreter's frame-by-frame decoding and matrix math, achieving up to 10x speedups with high rendering throughput.

### Threaded Python Processing
When drawing telemetry layouts onto videos, the application employs a 3-thread concurrent pipeline (decoding, processing/drawing, and encoding running in parallel) with native BGR in-place frame processing to prevent redundant color-space conversions and maximize GUI/CPU core utilization.

### Metadata Handling
Powered by **PyExifTool**, UWMedia ensures that your processed files are not "blank" videos. It copies all vendor-specific tags and correctly handles the complex timezone offsets found in DJI, Sony, and GoPro files. It also injects location, timezone, and matched dive log dates directly into generated overlays.


### Layout Validation
To ensure reliability during batch processing, UWMedia validates HUD layouts against the actual dive telemetry before starting the render. It checks for:
- **Field Existence**: Verifies that requested telemetry fields (depth, temp, etc.) exist in the data model.
- **Tank Serial Matching**: Alerts users if the layout expects tank data (e.g., from a Garmin transmitter) that isn't present in the provided log files.
- **JSON Integrity**: Ensures layouts are correctly formatted and skin assets are accessible.

## License

[MIT License](LICENSE)

## Credits
- Color Algorithm: [bornfree](https://github.com/bornfree) - This is not used anymore but gave me the idea!
- Metadata: [ExifTool by Phil Harvey](https://exiftool.org/)
- Processing: [FFmpeg](https://ffmpeg.org/)
