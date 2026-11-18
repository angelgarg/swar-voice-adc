"""Join rendered frames into an MP4 with Blender's own encoder (no ffmpeg needed).

  blender -b -P encode_video.py -- <frames dir> <out.mp4> [hold seconds on the last frame]
"""
import glob
import os
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
src, out = os.path.abspath(argv[0]), os.path.abspath(argv[1])
hold = float(argv[2]) if len(argv) > 2 else 2.0
frames = sorted(glob.glob(os.path.join(src, "f_*.png")))
assert frames, "no frames in " + src

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
FPS = 24
se = scene.sequence_editor_create()
strip = se.sequences.new_image("frames", frames[0], 1, 1)
for f in frames[1:]:
    strip.elements.append(os.path.basename(f))
n = len(frames)
tail = se.sequences.new_image("hold", frames[-1], 2, n + 1)
tail.frame_final_duration = int(hold * FPS)

scene.frame_start, scene.frame_end = 1, n + int(hold * FPS)
scene.render.fps = FPS
scene.render.resolution_x, scene.render.resolution_y = 1280, 720
scene.render.resolution_percentage = 100
scene.view_settings.view_transform = "Standard"      # frames are already tone-mapped
scene.render.image_settings.file_format = "FFMPEG"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
scene.render.ffmpeg.constant_rate_factor = "HIGH"
scene.render.ffmpeg.ffmpeg_preset = "GOOD"
scene.render.filepath = out
scene.render.use_file_extension = False
bpy.ops.render.render(animation=True)
print("ENCODED", out, n, "frames")
