#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root_dir"

segments_dir="assets/narration-segments"
mkdir -p "$segments_dir"
rm -f "$segments_dir"/*

concat_file="$segments_dir/concat.txt"
: > "$concat_file"

tail -n +2 narration-scenes.tsv | while IFS=$'\t' read -r id duration text; do
  text_file="$segments_dir/scene-${id}.txt"
  aiff_file="$segments_dir/scene-${id}.aiff"
  raw_file="$segments_dir/scene-${id}-raw.wav"
  fit_file="$segments_dir/scene-${id}-fit.wav"
  padded_file="$segments_dir/scene-${id}-padded.wav"

  printf '%s\n' "$text" > "$text_file"
  say -v Tingting -r 260 -f "$text_file" -o "$aiff_file"
  ffmpeg -y -i "$aiff_file" -ac 2 -ar 48000 "$raw_file" >/dev/null 2>&1

  actual="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$raw_file")"
  target="$(awk -v d="$duration" 'BEGIN { printf "%.3f", d - 0.35 }')"
  ratio="$(awk -v a="$actual" -v t="$target" 'BEGIN { r = a / t; if (r < 1) r = 1; printf "%.5f", r }')"

  ffmpeg -y -i "$raw_file" -filter:a "atempo=${ratio}" -ac 2 -ar 48000 "$fit_file" >/dev/null 2>&1
  ffmpeg -y -i "$fit_file" -af apad -t "$duration" -ac 2 -ar 48000 "$padded_file" >/dev/null 2>&1
  printf "file '%s/%s'\n" "$root_dir" "$padded_file" >> "$concat_file"
done

ffmpeg -y -f concat -safe 0 -i "$concat_file" -c:a pcm_s16le assets/narration.wav >/dev/null 2>&1
ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 assets/narration.wav
