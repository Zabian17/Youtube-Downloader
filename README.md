# YouTube Downloader

A modern, feature-rich graphical user interface for yt-dlp, built with Python and Tkinter. This application simplifies the process of downloading media from YouTube while offering advanced features such as a queue system, download history, and extensive UI customization.

## Features

- **Multiple Download Modes**: Support for downloading Video, Audio (MP3), Subtitles, and Thumbnails.
- **Queue Management**: Add multiple URLs to the queue and download them sequentially.
- **Download History**: Automatically tracks previously downloaded files with options to open the file or its directory directly from the application.
- **Smart URL Detection**: Monitors the clipboard for YouTube URLs and provides a quick-action prompt.
- **Drag and Drop**: Drag and drop URLs directly into the application to queue or preview them.
- **Customization**: 
  - Multiple built-in color themes.
  - Adjustable panel transparency and background dimming.
  - Custom background wallpaper support.
- **Quality Selection**: Choose specific video resolutions (up to 4K) and audio bitrates.
- **Auto-Cleanup**: Automatically removes temporary files (`.part`, `.ytdl`) if a download fails or is cancelled.

## Prerequisites

1. **Python 3.8** or higher.
2. **FFmpeg**: Required for merging video and audio streams, and for MP3 conversion.
   - Windows: You can install it via Winget using `winget install Gyan.FFmpeg`, or download it from the official website and add it to your system PATH.

## Installation

1. Clone or download this repository.
2. Navigate to the project directory.
3. Install the required Python dependencies:

```bash
pip install -r requirements.txt
```

*Note: The `requirements.txt` includes `yt-dlp`, `Pillow` (for image rendering), and `tkinterdnd2` (for drag-and-drop functionality).*

## Usage

Run the main Python script to launch the application:

```bash
python youtube_downloader.py
```

- **Video/MP3 Mode**: Paste a link, select your desired quality, and click Download.
- **Queue**: Use the "Queue" button to add items, then click "Start Queue" to process them sequentially.
- **Settings**: Access the Settings panel via the footer to change default output directories, themes, and UI transparency.

## Disclaimer

This tool is intended for personal use and for downloading content where you have the right to do so. Please respect copyright laws and the terms of service of the platform.
