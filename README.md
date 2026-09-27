# UWMedia (Underwater Media Processor)

<p align="center">
  <a href="https://skillicons.dev">
    <img src="https://skillicons.dev/icons?i=python,bash,git,md" alt="Tech Stack" />
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

Photo with Telemetry data (old overlay)
![DSC06641_color_garmin_overlay.jpg](media/DSC06641_color_garmin_overlay.jpg)


## [Example (YouTube)](https://youtu.be/8r8_4H4iOMg) (will be updated)

## Key Features

- **Batch Processing**: Process entire directories of videos and photos in one command.
- **Fast 3D LUT Color Pipeline**: Dynamic 3D LUT (`.cube`) generation from profile settings, executing color correction natively in FFmpeg to bypass Python overhead and speed up vs processing frame by frame.
- **Advanced Color Correction**: Underwater color restoration with custom profiles (vivid, subtle, default) saved in `color.yaml`.
- **Telemetry Overlay (HUD)**: Synchronize dive logs from Garmin (.FIT), Subsurface (.XML), and Shearwater (.UDDF) to create dynamic telemetry overlays.
- **Batch Telemetry Overlays (`--render-video-log`)**: Automatically generate matching black-background overlay videos/photos for all raw files in a folder, preserving creation timestamps and duration.
- **Metadata Integrity**: Preserves original camera metadata (QuickTime, DJI, Sony) and injects correct timezone/location information.
- **Dynamic Naming**: Automatically rename files based on the "Date Taken" metadata (`YYYYMMDD_HHMMSS`).
- **Overlay Templates & Designer**: Built-in overlay templates per dive computer (Garmin x50i/mk3i, Shearwater Perdix 2/3, Petrel, Peregrine, Teric, Tern, generic) with live state badges and colour rules, plus a full designer to modify them or build your own from any background image.
- **Log-to-Video Generation**: Create HEVC telemetry-only videos directly from dive logs on a black background, with size automatically adjusted to layout dimensions.
- **FCPXML Support**: Automatically generates `.xml` files for rendered telemetry videos for instant import into Final Cut Pro.
- **Layout Validation**: Automatic verification of HUD layouts against loaded dive logs to prevent errors during processing.
- **Dive Profile Builder**: Draw a synthetic open circuit, sidemount or CCR dive and save it as a UDDF, Garmin FIT or Subsurface log, to test overlays in situations like deco or gas switches. *Test data only - not for dive planning.*

### Workflow (how I do)
- **Run Color Correction** for all videos and photos.
- **Telemetry Creation**: for each corrected video, generate matching overlays (often several versions).
- **Import** videos and overlays into one folder in the video editor (I use Final Cut Pro).
- **Synchronized Clip**: create a sync clip per video and pick the overlay for it.
- **Create the Video** as normal - with the overlay as a separate layer, things like stabilisation are easy.

More detail in [Getting started → Typical workflow](docs/getting-started.md#typical-workflow).

## Installation

Download the app from the [Releases](../../releases) page (Windows/macOS/Linux), or run from source (Python 3.10+, FFmpeg and ExifTool in your `PATH`):

```bash
git clone https://github.com/MickeMannen/UWMedia.git
cd UWMedia
pip install -r requirements.txt
python -m uwmedia          # desktop app
python cli_main.py --help  # command line
```

See [Getting started](docs/getting-started.md) for the macOS download options and where your files are stored, and [Building the app](docs/building.md) to package it yourself.

## Documentation

The full documentation is in [`docs/`](docs/README.md):

| | |
|---|---|
| **The app** | [Color](docs/color.md) · [Overlay Generator](docs/overlay-generator.md) · [Convertion](docs/convertion.md) · [Color Tuning](docs/color-tuning.md) · [Tag Editor](docs/tag-editor.md) · [Log Viewer](docs/log-viewer.md) · [Overlay Designer](docs/overlay-designer.md) · [Dive Profile Builder](docs/dive-profile-builder.md) · [Advanced](docs/advanced.md) |
| **Reference** | [Command line](docs/cli.md) · [Configuration files](docs/configuration.md) · [Building](docs/building.md) · [How it works](docs/technical.md) |

<p align="center">
  <img src="media/main.png" alt="Color page" width="800">
</p>

Quick CLI example - colour-correct a folder and add a telemetry overlay:

```bash
python cli_main.py ./raw/ ./out/ --logs ./dive_logs/ --layout skins/perdix.zip --color
```

Please share if you make a fancy overlay!

## License

[MIT License](LICENSE)

## Credits
- Color Algorithm: [bornfree](https://github.com/bornfree) - This is not used anymore but gave me the idea!
- Metadata: [ExifTool by Phil Harvey](https://exiftool.org/)
- Processing: [FFmpeg](https://ffmpeg.org/)
