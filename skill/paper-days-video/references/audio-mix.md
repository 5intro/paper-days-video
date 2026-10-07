# Audio preparation and verification

## Sources and scope

Use the authorized bundled `assets/music/observation-deck.mp3` as the default bed. Copy it into the current project before mixing; all mixer paths are relative to that project. Keep its provenance with the package. The helper never downloads music or modifies source audio.

`compose_music.py` is an optional deterministic fallback for a new sample-free instrumental. It synthesizes oscillators with NumPy/SciPy, uses the supplied seed, and writes a float WAV plus a `.music.json` sidecar. It needs no model or internet connection. Its oscillator composition metadata is not a human listening approval or an assurance of exclusive rights to common musical building blocks.

Required runtime dependencies: Python 3.11 or 3.12, NumPy, SciPy, FFmpeg and ffprobe. Override the executables with `FFMPEG`/`FFPROBE`, or `--ffmpeg`/`--ffprobe`. Paths containing spaces work; the scripts never assemble shell command strings.

## Inputs

The timeline is an ordered, non-overlapping JSON list. A wrapper with a `segments` or `timeline` list is also accepted:

```json
[
  {
    "segment_id": "01",
    "start": 0.0,
    "voice_end": 4.25,
    "end": 5.0,
    "audio_path": "voice/01.wav",
    "first_activity_s": 0.08,
    "last_activity_s": 4.12
  }
]
```

- `start`, `voice_end` and `end` are absolute project seconds.
- `start` places the full voice clip, including its existing leading silence.
- `voice_end - start` must match the decoded source duration, to about 1 ms. Padding belongs after `voice_end` and before `end`.
- `first_activity_s` and `last_activity_s` are offsets within that source clip. They bound speech detection, not clip trimming. Omitted values use the full clip.
- The next segment begins at or after the previous segment’s `end`.
- `audio_path` is relative to the project root, not the timeline file’s folder. Absolute paths, escape paths and symlinks escaping the project are rejected.

The mixer assembles `voice_timeline.wav` itself. Do not assemble or time-stretch the narration again. Sample-rate conversion to 48 kHz preserves playback speed. Stereo voice sources are centered to mono; provide intentional multi-channel dialogue as separately prepared inputs only after reviewing that conversion.

`--sfx` accepts either an already aligned audio stem beginning at project time zero, or a JSON list:

```json
[
  {"audio_path": "sfx/paper.wav", "start": 8.2, "gain_db": -9.0}
]
```

SFX are used at their supplied level plus optional event gain. They are not automatically normalized. Set restrained levels in production, especially under narration. An event or aligned stem longer than the timeline is rejected rather than silently cut. Omit `--sfx` when there are no effects.

## Commands

```sh
python scripts/mix_audio.py --project ./episode --timeline timeline.json \
  --music assets/music/observation-deck.mp3 --out mix.wav

python scripts/mix_audio.py --project ./episode --timeline timeline.json \
  --music assets/music/observation-deck.mp3 --sfx sfx/events.json \
  --out mix-with-sfx.wav

python scripts/audit_media.py ./episode/final.mp4 --out ./episode/final.audit.json

# Optional alternative source, not the default when the bundled bed is available:
python scripts/compose_music.py --duration 120 --seed 17 --out ./episode/music/original.wav
```

Existing output, report or stem directories are not overwritten. Use a new `--out` for a new version. The renderer defaults to project `mix.wav`; if you use another filename, set the project config’s `mix_path` to that same project-relative filename. The composer also refuses to overwrite an existing WAV or sidecar.

The mixer writes:

- The requested WAV: stereo, 48 kHz, float32.
- `<mix-name>.report.json`: input hashes, timeline duration, dynamics, phrase ducking, objective margins, source preservation, loudness and peak measurements.
- `<mix-name>_stems/voice_timeline.wav`, `music_ducked.wav`, `sfx_timeline.wav`, `timeline.json`, 10 ms automation and speech-window audit JSON.

Stems are pre-master. The report’s `master_constant_gain_db` is the common gain used in the final WAV; do not compare a pre-master stem’s level directly with a mastered export. Temporary AAC and analysis audio are removed automatically. Only the report is retained from the AAC preview.

## Balance and dynamics

Music is audible but held behind speech. The default method follows these priorities:

1. Music-only EQ: a 65 Hz high-pass, broad reductions around 1.7 and 3.3 kHz, and an 11 kHz low-pass.
2. Slow music loudness automation at 1.8:1, bounded to +2.5 / −3.5 dB, using centered three-second EBU R128 short-term measurements. A short source without a complete three-second window uses a documented 400 ms RMS fallback. Smoothing is 0.8 seconds and gain slew is limited to 1 dB/s. Quiet fades are not boosted.
3. Music standalone constant gain targets −16 LUFS with a −3 dBTP ceiling. The fitted bed then starts about 10 LU below narration, with a −10 dBTP bed ceiling. The ceiling can make the bed lower than the target.
4. Speech ducking begins at a shallow −1.5 dB. Each phrase uses one stable adjustment from the lower decile of well-voiced 400 ms windows, rather than the faintest trailing syllable. The selected windows require at least 80% detected activity and voice RMS of at least −30 dBFS.
5. Anticipatory raised-cosine attack: 0.14 seconds; hold: 0.30 seconds; release: 1.15 seconds. Gaps recover by at most 2 dB relative to adjacent protected phrases. High-energy music and SFX protection are combined with speech protection; total adaptive ducking is capped at 4 dB. This is separate from the slow music-only dynamic control.
6. Music receives a 0.65 second entrance and a 1.2 second finish fade. Voice timing and speed are unchanged.
7. Final mastering is constant gain only. It approaches −16 LUFS only while preserving a −1.8 dBTP ceiling; it does not compress narration or force loudness through hard limiting. A lower achieved loudness is reported.
8. By default a temporary 192 kb/s AAC preview is encoded and remeasured. If its decoded peak exceeds −1.8 dBTP, common master gain is reduced with additional headroom. `--skip-aac-check` explicitly marks this check unverified. Always remeasure the actual final video, because its encoder settings may differ.

The CLI exposes `--bed-below-voice-db 10`, `--duck-db 1.5` and `--duck-limit-db 4` as independent controls. Duck amounts are nonnegative; the shallow amount cannot exceed the total cap. The stable speech-window margin follows `--bed-below-voice-db`. Actual values are recorded in the report. The documented 5 dB lower-percentile and 9 dB median review thresholds stay conservative even if you intentionally choose a closer balance.

Overall base music gain and the extra 1.5–4 dB duck are distinct stages. The final integrated voice/music difference will usually exceed 10 LU because ducking and fades are applied afterward. Reports expose this value instead of pretending the target was exact.

## Extending music without changing speed

The bundled source is about 178.965 seconds. Typical shorter episodes use a trimmed source and a gentle final fade; no loop is needed. If the source is too short, the default is a clear error, never a silently missing bed or time stretching.

For extension, the producing agent should analyze and audition candidate musical boundaries, then provide a project-local cue file. Do not call an energy trough or envelope match a verified phrase boundary. A cue file has this structure; the times below illustrate the schema only and are not verified cues for the bundled track:

```json
{
  "phrase_boundaries_s": [12.0, 24.0, 36.0, 48.0],
  "outro_start_s": 60.0,
  "crossfade_seconds": 2.0
}
```

```sh
python scripts/mix_audio.py --project ./episode --timeline timeline.json \
  --music music/authorized.wav --music-cues music/reviewed-cues.json \
  --music-end-policy crossfade_extend --out mix-extended.wav
```

A sibling `.music.json` is detected automatically. Among caller-provided phrase boundaries before the protected outro, the tool ranks compatible outgoing/incoming windows by objective RMS-envelope difference. It repeats a whole phrase region using complementary raised-cosine crossfades. These weights sum to one to avoid increasing gain for correlated material. If the required duration is not a whole phrase multiple, it trims excess from the beginning, then fades in. This may change the opening, which is explicitly reported. The original ending remains at the end, subject to the final fade and common mix gain. No pitch or speed change is performed.

The edit report includes boundary times, repeat count, crossfade duration, beginning trim and selection score. Audit the joins and the new opening by listening. For a duration where this edit is unsuitable, use a newly composed bed of the required duration or revise cues; do not insert silence unnoticed. Automatically composed beds normally already have the requested duration and need no extension.

## Objective checks and listening review

`audit_media.py` records stream properties, duration, a file hash, first-audio-stream integrated loudness, loudness range and true peak. Non-finite silence measurements appear as JSON `null`, not invented values. It omits arbitrary media tags and source filesystem paths from its report.

The mix report includes 400 ms, one-second and three-second speech/music RMS margins. Weak or sparsely voiced windows are excluded from these summary statistics, but this does not establish intelligibility. A low lower-percentile or typical margin creates a review flag. AAC preview measurements are engineering evidence only.

After rendering, listen through the complete actual export, especially quiet speech, rapid phrasing, pauses, transitions and the final sentence. Check that the bed is audible, not tiring, and does not pump; that SFX support the scene; and that phrase edits and fades sound natural. Inspect video and subtitles separately. Never report listening, visual review, clean ASR or runtime tests as complete unless those actions actually happened.
