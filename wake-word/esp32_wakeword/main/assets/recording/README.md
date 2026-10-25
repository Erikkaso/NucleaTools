# Recording Sounds

- `onsfx.pcm`: wakeword accepted; plays before recording (0.85 s).
- `offsfx.pcm`: recording finished; plays before upload (about 0.63 s).
- `source/`: original supplied audio files, preserved without modification.

Both runtime files are signed PCM16 little-endian, mono, 24000 Hz, without
a WAV header. CMake embeds only the two `.pcm` files, not the sources.
Moving these files did not change their audio, gain, or configured volume.

To regenerate from this directory with FFmpeg installed:

```powershell
ffmpeg -y -i source/onsfx.mp4 -map 0:a:0 -af "atrim=start=0.53:end=1.38,asetpts=PTS-STARTPTS" -ac 1 -ar 24000 -c:a pcm_s16le -f s16le onsfx.pcm
ffmpeg -y -i source/offsfx.mp4 -map 0:a:0 -af "volume=6.63dB" -ac 1 -ar 24000 -c:a pcm_s16le -f s16le offsfx.pcm
```

These trim/gain values apply to the supplied originals; review them when
replacing a source. Normal firmware builds do not need FFmpeg.
