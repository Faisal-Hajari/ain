# rtsp-video-streaming

A video source for AIN: point it at a folder of video files and it serves them
over RTSP as one continuous, never-ending stream, the way a camera would. When
the last file finishes it starts again from the first, and clients that are
already watching just keep watching — they never see the switch.

Useful for feeding recorded footage into the analytics pipeline, and for giving
the dashboard something live to show without a real camera on the network.

```bash
rtsp-video-streaming /path/to/videos
# streaming on rtsp://192.168.1.10:8554/live
```

Play it with anything that speaks RTSP:

```bash
ffplay -rtsp_transport tcp rtsp://192.168.1.10:8554/live
```

```bash
vlc rtsp://192.168.1.10:8554/live
```

## Run it with Docker

The image is built and published by
[`build-images.yml`](../../.github/workflows/build-images.yml) on every push to
`main`:

```bash
docker run --rm -p 8554:8554 -v /path/to/videos:/videos:ro ghcr.io/faisal-hajari/ain/rtsp-video-streaming:latest
```

Anything after the image name is passed straight to the CLI, so the folder
inside the container and every option below can be overridden:

```bash
docker run --rm -p 8554:8554 -v /path/to/videos:/videos:ro ghcr.io/faisal-hajari/ain/rtsp-video-streaming:latest /videos --size 1920x1080 --fps 30
```

Prefer `-rtsp_transport tcp` in clients when the server runs in a container:
RTP over UDP goes out from ports that are not published.

## Install locally

Requires Python 3.9+ and ffmpeg (with `libx264`) on the PATH.

```bash
sudo apt install ffmpeg   # or: brew install ffmpeg
```

```bash
pip install -e applications/rtsp-video-streaming
```

## How it works

- **One encoder, many viewers.** A single ffmpeg process re-encodes the current
  file and pushes RTP to the server over loopback; the server fans those packets
  out to every connected client. Ten viewers cost one encode, not ten.
- **Seamless looping.** ffmpeg is restarted for each file, so every file arrives
  with its own sequence numbers and timestamps. The server renumbers all of them
  onto a single continuous RTP stream anchored to one shared clock, so a client
  connected during file 1 keeps playing through files 2, 3, … and back around.
- **Uniform output.** Every file is normalised to the same resolution, frame
  rate and codecs, because clients negotiate the stream once and that
  description has to stay true for the whole loop. Mixed resolutions, frame
  rates, codecs and containers in the folder are fine.
- **Files without audio** get generated silence, so the audio track never
  disappears mid-loop.
- **Live folder.** The folder is rescanned at the start of every pass, so files
  added or removed while the server runs are picked up without a restart.
- **Join any time.** Parameter sets are advertised in the SDP and repeated
  in-band on every keyframe, so a client that connects mid-file starts decoding
  at the next keyframe (one per second by default).

## Usage

```
rtsp-video-streaming FOLDER [options]

  --host ADDR         bind address (default: 0.0.0.0)
  --port PORT         RTSP port (default: 8554)
  --path PATH         stream path (default: live)
  --size WxH          output resolution, or 'source' (default: 1280x720)
  --fps N             output frame rate (default: 25)
  --bitrate RATE      video bitrate (default: 2M)
  --gop N             keyframe interval in frames (default: one per second)
  --preset NAME       x264 preset (default: veryfast)
  --no-audio          stream video only
  --extensions LIST   comma separated extensions to play
  --recursive         also scan subfolders
  --shuffle [--seed N]  shuffle each pass
  --ffmpeg PATH / --ffprobe PATH   explicit binary paths
  --log-level LEVEL   debug, info, warning or error
```

Examples:

```bash
rtsp-video-streaming ./clips --port 8554 --path camera1 --size 640x480 --fps 15
```

```bash
rtsp-video-streaming ./clips --recursive --shuffle --no-audio --bitrate 4M
```

`--size source` keeps each file's own resolution. Only use it when every file
already has the same one: if the resolution changes mid-loop, clients have to
reconnect to pick up the new format.

## Supported RTSP

`OPTIONS`, `DESCRIBE`, `SETUP`, `PLAY`, `PAUSE`, `TEARDOWN`, `GET_PARAMETER`,
`SET_PARAMETER`, over unicast RTP — either interleaved on the TCP control
connection (`RTP/AVP/TCP`, the most firewall-friendly option) or over UDP
(`RTP/AVP`). Video is H.264, audio is G.711 A-law. RTCP sender reports are sent
so clients can keep audio and video in sync. Multicast is not supported.

## Development

```bash
cd applications/rtsp-video-streaming && pip install -e '.[dev]' && pytest
```

The tests cover the RTSP handshake, the RTP renumbering that makes the loop
seamless, the playlist and the encoder command line. None of them need ffmpeg
installed.
