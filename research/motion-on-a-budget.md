# Motion on a budget: masked motion, parallax and in-betweening

Date: 2026-11-25. Scope: cutting paid image-to-video (I2V) use for a 60–90 s vertical (9:16) low-poly film with about 11 shots. All prices are list prices on the date above. WaveSpeed pages say documentation prices "may be outdated" and that the live charge wins, so check the Generate-button estimate before a batch run.

Facts about our own pipeline come from the repo: `storyboard.json` has 11 shots of 6–8 s (74 s total, 8 `video` shots, 3 `kenburns` shots). `edit.fps` is 24. `pipeline/assemble.py` already stretches short clips up to `MAX_SLOWDOWN = 1.6` with `setpts`, then holds the last frame.

## Summary

- **The planned video endpoint already does first/last-frame in-betweening.** WaveSpeed `wan-2.2/i2v-480p-ultra-fast` takes an optional `last_image` at the same $0.05 per 5 s ($0.01/s). We don't need a separate FLF2V model or provider. [WaveSpeed API docs](https://wavespeed.ai/docs/docs-api/wavespeed-ai/wan-2.2-i2v-480p-ultra-fast)
- **Region-limited motion is cheapest by compositing, not by a hosted mask API.** Generate one normal $0.05 clip at 480p. Then keep only a masked region (face, hands, steam) and paste it onto the full-resolution still with NumPy/OpenCV or FFmpeg. Everything outside the mask stays pixel-still. Hosted mask options cost 4–6x more: Wan VACE masked video is $0.30 per 5 s on WaveSpeed and about $0.20 on fal, and the Kling motion brush on fal is $0.225.
- **Masked shots can be stretched or looped for free.** A cinemagraph region can ping-pong or crossfade-loop to any length. That removes the need for 8 s clips ($0.08) on ambient shots.
- **Parallax from depth is free and runs locally.** Run Depth Anything V2 Small (24.8M params, Apache-2.0) once per still. Then displace the image per frame with OpenCV, or use DepthFlow (`pip install depthflow`, OpenGL). Use it on wide or landscape shots. Keep the motion small on characters, because their edges stretch.
- **Use RIFE frame interpolation as the default "stretch" step.** Wan outputs 16 fps (fal bills "video seconds" at 16 fps). Our assembly converts to 24 fps by duplicating frames. `rife-ncnn-vulkan` has a Windows binary, a cp312 Windows wheel, Intel Vulkan support and a CPU mode (`-g -1`). Keep slow-motion at or under about 1.25x for characters and 1.6x for ambient motion.
- **Skip ToonCrafter and its successors.** ToonCrafter is built for 2D cartoons at 512×320 and 16 frames and needs about 10–27 GB of VRAM. ToonComposer needs about 57 GB. Neither suits low-poly 3D.
- **Recommended plan for the current storyboard:** 7 paid 5–8 s clips (4 of them masked). That is $0.38 list and about $0.51 with expected retries, against about $1.14 for "every shot full I2V, length-matched, with retries" (about 55% less). A lean variant with 4 paid clips comes to about $0.30 (about 74% less). At about $0.50 a film, the $1 free credit covers about 2 films instead of about 1.
- **Hosted motion control (Wan ATI, Wan-Move, Kling motion brush) is possible but not worth it yet.** It costs 4x or more per clip, and the trajectory inputs are hard to author from a CLI. Open-source ATI and Wan-Move are 14B models, which is impractical on a T4 with 6 GPU hours.

## Baseline we are comparing against

| Baseline | How | List cost | With retries (x1.5) |
|---|---|---|---|
| A: 11 x 5 s clips, stretched | 11 x $0.05 | $0.55 | ~$0.83 |
| B: length-matched (6 s shots get 5 s clips, 7–8 s shots get 8 s clips) | 4 x $0.05 + 7 x $0.08 | $0.76 | ~$1.14 |

The x1.5 retry factor is our assumption (about one retry for every two shots). It is not a measured rate. Prices: [WaveSpeed 480p ultra fast](https://wavespeed.ai/models/wavespeed-ai/wan-2.2/i2v-480p-ultra-fast), with $0.05 for 5 s and $0.08 for 8 s.

---

## 1. Region-limited motion (cinemagraph style)

### 1a. Composite route (recommended): generate once, mask onto the still

**What it is.** Make a normal I2V clip from the keyframe. Then blend it back onto the original keyframe through a soft mask. Only the masked region moves. Bad motion outside the mask (melting background, drifting faces of side characters) is thrown away. That also lowers the retry rate, since only the region has to look right.

**How we'd run it (all local, CPU, deterministic):**

1. Clip: WaveSpeed `wavespeed-ai/wan-2.2/i2v-480p-ultra-fast`, 5 s, $0.05 ([docs](https://wavespeed.ai/docs/docs-api/wavespeed-ai/wan-2.2-i2v-480p-ultra-fast)). Put "static locked-off camera, background does not move" in the prompt so the clip lines up with the still.
2. Mask: pick one of these.
   - A shape in the storyboard, such as `motion.mask = {shape: ellipse, x, y, w, h, feather}` in normalised coordinates. This is the simplest and fully deterministic.
   - A subject mask from rembg (`pip install "rembg[cpu]"`; models `u2net`, `isnet-anime`, `birefnet-general`, `sam`; `-om` returns only the mask). It needs Python >=3.11 and <3.14, so it works on 3.12. [rembg README](https://github.com/danielgatis/rembg)
   - An automatic mask from the clip itself: the per-pixel frame-difference or optical-flow magnitude (OpenCV `calcOpticalFlowFarneback`), intersected with the storyboard shape. This keeps only pixels that actually moved.
3. Align: upscale the 480p clip to the keyframe size. If the model nudged the camera, register each frame to the still (OpenCV `findTransformECC`) before blending.
4. Colour match: Wan output can drift in colour against the FLUX still. Match the mean and standard deviation per channel inside the mask, using the region from the clip's first frame and the same region in the still.
5. Blend: `out = still * (1 - a) + clip * a`, with `a` a mask feathered by Gaussian blur (8–20 px at 1080 px tall). Do this in NumPy and pipe frames to FFmpeg. FFmpeg's `maskedmerge` filter can do the same blend, but all three inputs must share a pixel format. [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html) (sections maskedmerge, alphamerge)
6. Extend (free):
   - Looping detail (steam, smoke, leaves, cloth): ping-pong (`split` + `reverse` + `concat`) or a crossfade loop (`xfade` from the tail onto the head).
   - One-off action (eyes closing, a laugh): RIFE stretch up to about 1.25x, then hold the last frame. `assemble.py` already does the hold with `tpad`.
   [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html) (sections reverse, loop, xfade, setpts)

**Cost and speed.** $0.05 per shot, often fewer retries. Local work is plain array math on about 120–200 frames, so expect seconds, not minutes (an estimate, not measured).

**Quality caveats for low-poly 3D.**
- Sharpness mismatch: the moving region is upscaled 480p, while the rest is the full-resolution still. Keep regions small or mid-frame, and add a little blur to the still at the seam if it shows.
- Faceted shading helps, because flat colours hide seams. But a large mask on a character whose body also needs to move looks wrong (a talking head on a frozen body). Mask the whole upper body when the face moves.
- Light changes in the clip (flicker) show up only inside the mask. Colour matching per frame, not just once, helps.

### 1b. Hosted mask or motion-brush APIs

| Option | Masking input | Price | Notes |
|---|---|---|---|
| WaveSpeed `wavespeed-ai/wan-2.1-14b-vace` | `mask_image`, `video`, `images` (0–5), `task` = depth/pose/face/inpainting/none, `size` incl. `480*832` | $0.30 for 5 s at 480p, $0.45 for 6–10 s, $0.40/$0.60 at 720p | [docs](https://wavespeed.ai/docs/docs-api/wavespeed-ai/wan-2.1-14b-vace) |
| fal `fal-ai/wan-vace-14b` | `mask_video_url`, `mask_image_url`, `first_frame_url`, `last_frame_url`, `ref_image_urls`, 240p–720p | $0.04/s at 480p (~$0.20 for 81 frames at 16 fps), $0.08/s at 720p | [fal llms.txt](https://fal.ai/models/fal-ai/wan-vace-14b/llms.txt) |
| fal Kling 1.0 standard I2V (motion brush) | `static_mask_url`, `dynamic_masks[{mask_url, trajectories[{x,y}]}]`, `tail_image_url`, 5 or 10 s | $0.045/s (~$0.225 for 5 s) | [fal llms.txt](https://fal.ai/models/fal-ai/kling-video/v1/standard/image-to-video/llms.txt). Old model. Third-party docs say masks and the tail image can't be combined, and masks must match the image resolution ([skills.sh](https://skills.sh/jeremylongshore/claude-code-plugins-plus-skills/klingai-image-to-video), [Magnific](https://docs.magnific.com/api-reference/video/post-kling-4k-i2v.md)). |
| fal Kling 1.6 Pro / 2.0 Master / 2.1 | `static_mask_url`, `dynamic_mask_url` (singular in some versions) | not checked per version | Field names differ by version ([fal Kling 2.0 Master docs](https://fal.ai/docs/model-api-reference/video-generation-api/kling-2.0-master)) |
| WaveSpeed Kling 1.6 Pro | `image`, `last_image`, no mask fields | $0.45 per 5 s in the README (button shows $0.09) | [model page](https://wavespeed.ai/models/kwaivgi/kling-v1.6-i2v-pro) |
| Runway API `POST /v1/image_to_video` | no mask, brush or region parameter | gen4_turbo 5 credits/s at $0.01/credit = $0.25 per 5 s | [API reference](https://docs.dev.runwayml.com/api/), [pricing](https://docs.dev.runwayml.com/guides/pricing/). Motion Brush is not in the API. |
| fal `fal-ai/wan-ati` (trajectory control) | trajectories on an image | price not readable | Model page found by search ([fal](https://fal.ai/models/fal-ai/wan-ati)), but it returned 404 on fetch. |
| fal `fal-ai/wan-move` (trajectory) | point tracks | price not readable | Also 404 on fetch. |

**Verdict.** VACE masked video is the "proper" version of 1a. It regenerates only the white mask region while keeping the rest. But it costs 4–6x more, and our compositing gives the same pixel-still background. Kling's motion brush adds direction control, but it is a 2024 model at 4.5x the cost. Use hosted masks only if compositing seams look bad in testing.

### 1c. Open-source masked or trajectory models on a Kaggle T4

| Model | What it does | Size | Fits a T4 (16 GB, fp16 only)? |
|---|---|---|---|
| Wan2.1-VACE-1.3B ([VACE repo](https://github.com/ali-vilab/VACE)) | MV2V masked video edit, "Animate-Anything", "Move-Anything". Inputs: `--src_video`, `--src_mask`, `--src_ref_images`. About 81 frames at 480×832. | 1.3B | Probably. The sibling T2V-1.3B "requires only 8.19 GB VRAM" ([Wan2.1](https://github.com/Wan-Video/Wan2.1)). Wan's reference code runs bf16, so fp16 on a T4 is untested here. |
| Wan2.1-VACE-14B | Same, up to 720p | 14B | No, not practical. |
| ATI ([bytedance/ATI](https://github.com/bytedance/ATI)) | Trajectory control (object, local, camera) on Wan2.1-I2V-14B-480P. Ships a localhost trajectory editor GUI. Kijai's ComfyUI nodes support it. | 14B | No. 14B parameters in fp16 is about 28 GB of weights, so it only runs with heavy offload or quantisation. That is too slow for 6 GPU hours (our arithmetic, not tested). |
| Wan-Move ([ali-vilab/wan-move](https://github.com/ali-vilab/wan-move), [paper](https://arxiv.org/html/2512.08765v1)) | Point-track motion control, 5 s at 832×480. Authors compare it to the Kling 1.5 Pro motion brush. | 14B | No. |
| Go-with-the-Flow ([paper](https://arxiv.org/abs/2501.08331), [HF mirror README](https://huggingface.co/spaces/OneOverZero/Go-With-The-Flow/blame/main/ORIGINAL_README.md)) | Warped-noise motion control and "cut and drag". CogVideoX-5B LoRAs. The workflow needs a GUI step (`cut_and_drag_gui.py`). | 5B | Unclear. A third-party blog says 11 GB with offload ([aifilms](https://studio.aifilms.ai/blog/go-with-the-flow-levitor-open-source-motion-video)). The official GitHub page was empty when fetched. |

**Verdict.** Only VACE-1.3B is a realistic T4 candidate. With about 6 GPU hours, it is a fallback, not the main path. A T4 is far slower than the RTX 4090 that Wan quotes at about 4 minutes per 5 s clip at 480p for 1.3B ([Wan2.1](https://github.com/Wan-Video/Wan2.1)). ComfyUI can be driven headlessly through its HTTP `POST /prompt` queue ([ComfyUI server routes](https://docs.comfy.org/development/comfyui-server/comms_routes)), but the official `generate.py` scripts are simpler to call from our CLI.

### 1d. Zero-cost procedural motion (no model)

For steam, smoke, mist, heat shimmer and water we can skip the model entirely:

- Displace the masked region with a scrolling noise texture (FFmpeg `displace`, or `cv2.remap` with a Perlin or sine field).
- Overlay a pre-rendered or procedurally made smoke sprite with low opacity, moving upward.

This is free and fully deterministic. It suits low-poly well when the effect is simple (two-tone smoke puffs). [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html) (section displace)

---

## 2. 2.5D parallax and camera moves from one still

**What it is.** Estimate a depth map once. Then for each frame, shift pixels by `offset * (depth - focal_depth)` to fake a dolly, orbit or slide. Near objects move more than far ones.

**How we'd run it.**

| Tool | Install | Runs on | Notes |
|---|---|---|---|
| Depth Anything V2 Small, `depth-anything/Depth-Anything-V2-Small-hf` | `transformers` `pipeline("depth-estimation", ...)` (pulls the PyTorch CPU wheel) | CPU | 24.8M params, Apache-2.0 ([model card](https://huggingface.co/depth-anything/Depth-Anything-V2-Small-hf)). Default input 518 px. |
| Same model as ONNX, `onnx-community/depth-anything-v2-small` | `onnxruntime` | CPU | Apache-2.0, lighter install than torch ([HF](https://huggingface.co/onnx-community/depth-anything-v2-small)). |
| Our own displacement | `opencv-python`, `numpy` | CPU | `cv2.remap` per frame; we control the camera curve. Fully deterministic. |
| DepthFlow | `python -m pip install depthflow`, then `depthflow main -o video.mp4`. Codec options go before `main`, such as `depthflow h264 --crf 23 main -o out.mp4`. Python API: `scene.main(output=..., fps=, time=, width=, height=, ssaa=)`. Use `backend=headless` in scripts. | OpenGL GPU (the Intel UHD 620 should work through its OpenGL driver; not tested) | AGPL-3.0. Uses Depth Anything v2 by default (`depthflow da2 --model small`). Needs FFmpeg on PATH. v1.0 has no built-in animation presets yet; you write the `update()` camera code. [docs](https://depth.tremeschin.com/), [PyPI page](https://depth.tremeschin.com/get/pypi/), [exporting](https://depth.tremeschin.com/docs/exporting/), [estimators](https://depth.tremeschin.com/docs/estimators/), [animation](https://depth.tremeschin.com/docs/animation/), [GitHub](https://github.com/BrokenSource/DepthFlow) |

**Speed at 480×854 (estimates, not measured on this laptop).**
- Depth: one inference per shot. Arm reports about 0.73 s for an INT8 CPU run on a phone at 518×686 ([Arm](https://developer.arm.com/ai/models/hugging-face/Arm/depth-anything-v2-small-int8-xnnpack-executorch-vivo-x300/depth-anything-v2-small-int8-pte)). Expect roughly 0.5–3 s on the i7-8650U in fp32.
- Displacement: `cv2.remap` on a 480×854 frame is a few milliseconds. 168 frames (7 s at 24 fps) should take well under 10 s, plus encoding.
- DepthFlow claims "8k50fps on an RTX 3060-class GPU" ([GitHub](https://github.com/BrokenSource/DepthFlow)). On the UHD 620 at 480×854 it should still beat real time, but this is not verified.

**Quality on low-poly 3D renders.**
- Good fit for landscapes, mountains, villages and rooms. Flat, faceted planes give clean depth layers, and small dolly or zoom moves look like a real 3D camera.
- Weak spots:
  - "Rubber-sheet" stretching at depth edges (a character against the sky).
  - Thin parts (hair, fingers, cup handles).
  - Large lateral moves that reveal hidden background.
- Mitigations:
  - Keep the offset to about 2–4% of the frame width, and prefer push-in or pull-out to sideways orbit.
  - Blur or dilate the depth map at edges.
  - For a strong move, cut the subject out (rembg), fill a clean background plate (a second FLUX.2 klein edit with "same scene, no people"), and move the two layers separately.
- Characters stay frozen, so parallax works for establishing shots and for shots where the people are small or still. Combine it with a masked cinemagraph (mist or smoke) to make the frame feel alive.

---

## 3. In-betweening

### 3a. First and last frame video (bridging two keyframes we already have)

| Endpoint | End-frame field | 480p price, 5 s | Notes |
|---|---|---|---|
| **WaveSpeed `wan-2.2/i2v-480p-ultra-fast`** | `last_image` (optional) | **$0.05** (8 s: $0.08) | Our current endpoint. [API docs](https://wavespeed.ai/docs/docs-api/wavespeed-ai/wan-2.2-i2v-480p-ultra-fast) |
| WaveSpeed `wan-2.2/i2v-720p-ultra-fast` | `last_image`, "Optional ending frame for start-to-end interpolation" | $0.10 (8 s: $0.16) | [model page](https://wavespeed.ai/models/wavespeed-ai/wan-2.2/i2v-720p-ultra-fast) |
| WaveSpeed `wavespeed-ai/wan-flf2v` (Wan 2.1 FLF2V 14B) | `last_image` (required) | $0.30 (10 s: $0.45) | [model page](https://wavespeed.ai/models/wavespeed-ai/wan-flf2v) |
| fal `fal-ai/wan/v2.2-a14b/image-to-video` | `end_image_url` | $0.04/s at 480p (~$0.20) | Also has built-in `interpolator_model` = film/rife, `num_interpolated_frames` 0–4. 16 fps default. [fal llms.txt](https://fal.ai/models/fal-ai/wan/v2.2-a14b/image-to-video/llms.txt) |
| fal Kling 1.0 standard | `tail_image_url` | ~$0.225 | [fal llms.txt](https://fal.ai/models/fal-ai/kling-video/v1/standard/image-to-video/llms.txt) |
| WaveSpeed Kling 2.1 Pro start-end | `last_image` (required) | $0.45 | [model page](https://wavespeed.ai/models/kwaivgi/kling-v2.1-i2v-pro/start-end-frame) |
| WaveSpeed Vidu Q3 Turbo start-end | `last_image` (required) | $0.20 at 540p | [model page](https://wavespeed.ai/models/vidu/q3-turbo/start-end-to-video) |
| Alibaba Model Studio `wan2.2-kf2v-flash` | first + last frame | $0.015/s at 480p (~$0.075) | Singapore region list price ([Alibaba Cloud](https://www.alibabacloud.com/help/en/model-studio/wan2-2-kf2v-flash)). Needs a separate account. |
| Runway API (wan3, kling3.0, veo3.1, seedance2 and others) | `promptImage[{uri, position: "last"}]` | wan3 5 credits/s = $0.25 per 5 s | gen4_turbo accepts `first` only. [API](https://docs.dev.runwayml.com/api/), [pricing](https://docs.dev.runwayml.com/guides/pricing/) |

**Can one clip bridge two keyframes?** Yes, at no extra price, through `last_image` on our endpoint. Use it when:
- The shot has a clear start and end state (a hand reaches out, then the girl is across the stream).
- Two storyboard shots share a location and can become one continuous move. That saves a clip and a cut.

How to get the end frame: make it with FLUX.2 klein on Cloudflare using the start keyframe as a reference image ("same scene, same characters, she is now across the stream"). This costs one extra free image per FLF shot. Keep the two frames close: same camera, same lighting, a modest pose change. Wan 2.2 at 5 s cannot convincingly bridge a big jump in camera angle.

### 3b. Frame interpolation (stretching clips, raising fps)

| Tool | Install on Windows | CPU or Intel iGPU | Notes |
|---|---|---|---|
| **rife-ncnn-vulkan** (nihui, release 20221029, models up to rife-v4.6) | Windows zip binary ([releases](https://github.com/nihui/rife-ncnn-vulkan)). The zip is ~430 MB because it bundles all models. | Vulkan on "Intel/AMD/Nvidia GPU". `-g -1` = CPU | `-n` sets the target frame count (v4 models support any timestep), `-s` the timestep, `-m` the model. [README](https://github.com/nihui/rife-ncnn-vulkan) |
| rife-ncnn-vulkan-python-tntwise 1.4.5 | `pip install rife-ncnn-vulkan-python-tntwise` (cp39–cp313 `win_amd64` wheels, incl. **cp312**) | Vulkan / CPU | [PyPI JSON](https://pypi.org/pypi/rife-ncnn-vulkan-python-tntwise/json). Which models it bundles was not checked. |
| Newer RIFE ncnn models (v4.25, v4.26) | VapourSynth plugin lists 4.25/4.26 ([styler00dollar](https://github.com/styler00dollar/VapourSynth-RIFE-ncnn-Vulkan)). TNTwise hosts exported models separately ([TNTwise fork](https://github.com/TNTwise/rife-ncnn-vulkan)). | Vulkan | Upstream says 4.25 is the default choice, "4.24+ is quite suitable for post-processing of some diffusion model generated videos", and that anime scenes improved in 4.25 ([Practical-RIFE](https://github.com/hzwer/Practical-RIFE)). |
| Practical-RIFE (PyTorch) | `inference_video.py --multi=2 --video=...`, `--fps` | CUDA mainly. Python <=3.11 required | [README](https://github.com/hzwer/Practical-RIFE). Use it on Kaggle, not on the laptop. |
| FILM (Google) | TensorFlow repo | Slow on CPU (not measured) | Built for large motion, up to about 100 px ([paper](https://arxiv.org/pdf/2202.04901)). Available server-side as `interpolator_model: "film"` on fal Wan 2.2. |
| FFmpeg `minterpolate` | already bundled | CPU | Classic motion-compensated interpolation. Free but produces warping artifacts on fast motion. [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html) (section minterpolate) |

**Speed on the UHD 620.** No published benchmark found. A rough guess is a few frames per second at 480×854 on Vulkan, and slower on CPU. A 5 s clip interpolated 2x (about 80 new frames) should take well under a few minutes. Measure it before relying on it.

**Where it breaks.**
- Fast or large motion: the model "has to guess" ([Practical-RIFE issue](https://github.com/hzwer/Practical-RIFE/issues/34)).
- Low source fps leaves bigger gaps ([VideoHelp](https://forum.videohelp.com/showthread.php?p=2674175)).
- Cuts produce ghosting, so interpolate each shot separately ([Topaz forum](https://community.topazlabs.com/t/frame-interpolation-best-settings-to-minimise-blurry-ghosting-effects/92804)).
- Characters: limbs crossing (walking legs, hands passing the face) smear or double.
- Low-poly edges: flat facets interpolate well, but hard silhouette edges against a contrasting background can show a one-frame halo.
- Scrolling or high-contrast thin lines can ghost ([Topaz forum](https://community.topazlabs.com/t/poor-frame-interpolation-on-scrolling-text/77351)).

### 3c. Stretch 5 s to 7–8 s, or 16 to 24/30 fps

- **16 fps to 24 fps: yes, do it.** Wan is natively 16 fps: fal bills "video seconds" at 16 fps and defaults to 81 frames at 16 fps ([fal](https://fal.ai/models/fal-ai/wan/v2.2-a14b/image-to-video/llms.txt)). Our assembly's `fps=24` then repeats every other frame, which judders on pans. RIFE to exactly 24 fps (`-n` = frames × 1.5) is a clear win at low risk. fal ships the same idea built in (`interpolator_model`).
- **5 s to 6 s (1.2x): fine** for almost anything, including faces.
- **5 s to 7 s (1.4x):** fine for ambient motion (smoke, mist, camera drift) and for the brief's "smooth and slow" style. Walking starts to look floaty.
- **5 s to 8 s (1.6x):** only for ambient or masked loops. For walking or talking, buy the 8 s clip ($0.08), or use 5 s plus a held last frame with a slow push-in.
- **Our current `setpts` stretch without interpolation** repeats frames. At 1.4–1.6x on a 16 fps source, that is visible stutter. Put RIFE in front of it and keep `MAX_SLOWDOWN` as the cap.
- Wan clips can already contain uneven motion between frames that looks like skips. One forum report found RIFE smoothed this ([VideoHelp](https://forum.videohelp.com/showthread.php?p=2793387)).

### 3d. Cartoon or stylised inbetweening (ToonCrafter and later)

| Model | Needs | Output | Fit for low-poly 3D |
|---|---|---|---|
| ToonCrafter ([repo](https://github.com/Doubiiu/ToonCrafter)) | "about 24G~27G", with community builds at about 10–12 GB fp16; A100 for the 24 s figure | 16 frames at 512×320 | Poor. Trained on 2D cartoons and line art. 16 frames is under 1 s at 24 fps, and the resolution is below our 480×854 portrait. |
| ToonComposer ([paper](https://arxiv.org/abs/2508.10881), [HF](https://huggingface.co/TencentARC/ToonComposer)) | about 57 GB VRAM for 480p, 61 frames; built on Wan2.1-I2V-14B | 480p / 608p | Not runnable on a T4. A hosted HF Space exists. |

**Verdict.** Skip both. Our frames are shaded 3D renders, not line art. Wan FLF through `last_image` does the same job for $0.05.

---

## 4. Shot-budget strategy

### How others mix shot types

Motion-comic and low-budget AI channels usually keep generative motion for a few "hero" beats (character action, emotion) and fill the rest with pan-and-zoom, parallax and single-detail cinemagraphs. One guide summarises the rule as "pan-and-zoom for simple movement, parallax for depth, cinemagraphs for one looping detail, AI image-to-video" for animated beats ([Renderforest](https://www.renderforest.com/blog/how-to-add-motion-to-still-images)). A published automated pipeline defaults to Ken Burns and falls back to it whenever a richer motion step fails, logging why ([dev.to](https://dev.to/dasein108/zero-to-autopilot-part-3-giving-a-still-image-real-motion-for-000-1a5b)). These are blog and vendor sources. We found no data that measures savings or engagement.

### Per-shot plan for the current storyboard (74 s, 11 shots)

| Shot | Length | Content (from `storyboard.json`) | Now | Proposed type | Paid clip |
|---|---|---|---|---|---|
| S01 | 7 s | Two figures walk down misty trail, pan right | video | `parallax` (slow slide) + procedural mist; frame the figures small | $0 |
| S02 | 7 s | Walking beside them, leaves brushing clothes | video | `full_i2v` 5 s, RIFE to 24 fps and 1.4x | $0.05 |
| S03 | 6 s | Mother reaches out, girl steps across stream | video | `flf_inbetween` (start: hand out; end: girl across), RIFE 1.2x | $0.05 |
| S04 | 7 s | Girl brings bean close, closes eyes, smoke | video | `masked_i2v` (face, hands, smoke region), 1.2x, hold plus slight push | $0.05 |
| S05 | 6 s | Hand picking beans | kenburns | `still_kenburns` | $0 |
| S06 | 8 s | Walk in profile, camera pans along | video | `full_i2v` 8 s (walking can't be stretched 1.6x) | $0.08 |
| S07 | 6 s | Feet walking on dusty earth | kenburns | `still_kenburns` (or `parallax`) | $0 |
| S08 | 7 s | She rotates the roasting pan, smoke | video | `masked_i2v` (pan, hands, smoke), ping-pong to 7 s | $0.05 |
| S09 | 7 s | Coffee pours, steam rises | video | `cinemagraph` (stream plus steam masked, crossfade loop) | $0.05 |
| S10 | 6 s | Grandmother laughs | video | `masked_i2v` (head and shoulders), RIFE 1.2x | $0.05 |
| S11 | 7 s | Zoom-out mountain vista | kenburns | `parallax` (pull-out) | $0 |

**Recommended ("balanced"):** 7 paid clips, all at 480p: 6 x $0.05 + 1 x $0.08 = **$0.38 list**. Retries: assume x1.5 on the 3 full or FLF clips and x1.2 on the 4 masked ones, which gives about **$0.51**. That is **about 55% below baseline B (about $1.14)** and about 40% below baseline A (about $0.83).

**Lean:** also make S02 a `masked_i2v` of hands and leaves, and S09 procedural (scrolling-noise stream plus smoke sprite). That leaves 4 paid clips (S03, S04, S06, S10): $0.23 list, **about $0.30** with retries, **about 74% below baseline B**.

| Plan | Paid clips | List | With retries | Films per $1 free credit |
|---|---|---|---|---|
| Baseline A (all 5 s) | 11 | $0.55 | ~$0.83 | ~1.2 |
| Baseline B (length-matched) | 11 | $0.76 | ~$1.14 | ~0.9 |
| **Balanced (recommended)** | 7 | $0.38 | ~$0.51 | ~2 |
| Lean | 4 | $0.23 | ~$0.30 | ~3 |

Extra free-tier use: about 1–2 extra FLUX.2 klein images per film (FLF end frames, clean background plates). That fits easily in the ~75/day free images.

---

## Recommended per-shot motion types

| `motion.mode` | When to use | Engine | Cost per shot |
|---|---|---|---|
| `full_i2v` | Whole-body action, walking, anything where most of the frame must move | WaveSpeed `wan-2.2/i2v-480p-ultra-fast`, 5 s (8 s if walking more than 6 s), then RIFE to 24 fps | $0.05 / $0.08 |
| `flf_inbetween` | Clear start and end state, or two story beats that can become one move | Same endpoint with `last_image`; end frame from FLUX.2 klein with the start frame as reference | $0.05 + 1 free image |
| `masked_i2v` | Faces, hands, one character acting while the scene stays still | Same endpoint, then mask (storyboard shape, rembg, or flow-derived), align, colour match, feather and blend onto the full-res still | $0.05 |
| `cinemagraph` | One looping detail: steam, smoke, pouring, cloth, leaves, water | `masked_i2v` plus ping-pong or crossfade loop to any length | $0.05 (or $0 with `procedural_fx`) |
| `procedural_fx` | Simple steam, mist, shimmer, drifting dust | FFmpeg `displace` / `cv2.remap` noise plus sprite overlay, local | $0 |
| `parallax` | Establishing, landscape, interiors, still characters | Depth Anything V2 Small (CPU), `cv2.remap` camera curve, or DepthFlow (OpenGL) | $0 |
| `still_kenburns` | Inserts, details, fallback when anything else fails | Existing FFmpeg `zoompan` in `assemble.py` | $0 |

Fallback chain per shot: `masked_i2v`/`full_i2v` → `parallax` → `still_kenburns`, logged in the run manifest.

---

## Could not verify

- How fast RIFE (`rife-ncnn-vulkan`) runs on the Intel UHD 620 or on CPU at 480×854. No published benchmark was found, and the 430 MB release zip was too slow to download for a local test.
- How fast Depth Anything V2 Small and DepthFlow run on this laptop, and whether DepthFlow's OpenGL renderer runs on the UHD 620 driver. Both are estimates above.
- DepthFlow's supported Python versions (the PyPI page does not say).
- Whether WaveSpeed's ultra-fast `last_image` truly pins the final frame. The 480p docs only say "the last image for generating the output", while the 720p page says "start-to-end interpolation". Test one clip.
- The fps and exact frame count of WaveSpeed ultra-fast output, and whether a 9:16 input gives a 480×832 portrait output (the page says resolution is "fixed at 480p").
- fal `fal-ai/wan-ati` and `fal-ai/wan-move` input schemas and prices (pages returned 404 when fetched).
- Kling motion-brush field names and prices for fal Kling 1.6 / 2.x, and the official Kling API's current motion-brush support and price.
- Whether Runway's `position: "last"` works on every model listed. The pricing and API pages were read, but no call was made.
- Whether Wan2.1-VACE-1.3B runs correctly in fp16 on a T4, and how long a clip takes there.
- Go-with-the-Flow VRAM needs (only a third-party figure). The official GitHub page appeared empty when fetched.
- Which RIFE models the `rife-ncnn-vulkan-python-tntwise` wheel bundles.
- The x1.5 / x1.2 retry factors in the cost tables are assumptions, not measurements.
