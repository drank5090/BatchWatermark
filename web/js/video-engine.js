/**
 * Pure-browser video preview frame extractor and Canvas + MediaRecorder watermark exporter.
 * Runs 100% locally in the browser with zero external dependencies or SharedArrayBuffer headers.
 */

import { PREVIEW_MAX_EDGE, buildOverlayCanvas } from "./watermark-engine.js";

function waitForEvent(target, eventName, errorEvent = "error", timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    let timer = null;
    const cleanup = () => {
      if (timer) clearTimeout(timer);
      target.removeEventListener(eventName, onSuccess);
      if (errorEvent) target.removeEventListener(errorEvent, onError);
    };
    const onSuccess = () => {
      cleanup();
      resolve();
    };
    const onError = () => {
      cleanup();
      reject(new Error("浏览器无法解码该视频格式或编码"));
    };
    target.addEventListener(eventName, onSuccess, { once: true });
    if (errorEvent) target.addEventListener(errorEvent, onError, { once: true });
    timer = setTimeout(() => {
      cleanup();
      reject(new Error("视频加载超时"));
    }, timeoutMs);
  });
}

/**
 * Probe video dimensions & duration and extract a crisp representative RGBA preview frame.
 */
export async function probeVideoAndExtractFrame(file, maxEdge = PREVIEW_MAX_EDGE) {
  const url = URL.createObjectURL(file);
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.preload = "auto";
  video.src = url;

  try {
    await waitForEvent(video, "loadedmetadata");
    const origW = video.videoWidth;
    const origH = video.videoHeight;
    const duration = Number.isFinite(video.duration) ? video.duration : 0;

    if (origW <= 0 || origH <= 0) {
      throw new Error("未能读取有效视频画面尺寸");
    }

    const seekTarget = duration > 0.6 ? Math.min(0.5, duration * 0.15) : 0;
    if (seekTarget > 0) {
      video.currentTime = seekTarget;
      await waitForEvent(video, "seeked");
    } else if (video.readyState < 2) {
      await waitForEvent(video, "loadeddata");
    }

    let pw = origW;
    let ph = origH;
    if (Math.max(origW, origH) > maxEdge) {
      const scale = maxEdge / Math.max(origW, origH);
      pw = Math.max(1, Math.round(origW * scale));
      ph = Math.max(1, Math.round(origH * scale));
    }

    const previewCanvas = document.createElement("canvas");
    previewCanvas.width = pw;
    previewCanvas.height = ph;
    const ctx = previewCanvas.getContext("2d");
    ctx.drawImage(video, 0, 0, pw, ph);

    return { previewCanvas, origW, origH, duration };
  } finally {
    video.pause();
    video.removeAttribute("src");
    video.load();
    URL.revokeObjectURL(url);
  }
}

/**
 * Pick the best supported MediaRecorder MIME type & file extension for this browser.
 */
function chooseRecorderFormat() {
  if (typeof MediaRecorder === "undefined") {
    throw new Error("当前浏览器不支持 MediaRecorder 视频录制导出");
  }
  const candidates = [
    { mimeType: "video/mp4;codecs=avc1.42E01E,mp4a.40.2", ext: ".mp4" },
    { mimeType: "video/mp4;codecs=avc1,mp4a.40.2", ext: ".mp4" },
    { mimeType: "video/mp4", ext: ".mp4" },
    { mimeType: "video/webm;codecs=vp9,opus", ext: ".webm" },
    { mimeType: "video/webm;codecs=vp8,opus", ext: ".webm" },
    { mimeType: "video/webm", ext: ".webm" },
  ];
  for (const c of candidates) {
    try {
      if (MediaRecorder.isTypeSupported(c.mimeType)) return c;
    } catch {
      // ignore
    }
  }
  return { mimeType: "", ext: ".webm" };
}

/**
 * Composite watermark overlay onto every video frame locally using Canvas + MediaRecorder.
 */
export async function exportWatermarkedVideo(
  item,
  config,
  exportConfig,
  renderOpts,
  onProgress,
  isCancelled,
) {
  const { mimeType, ext } = chooseRecorderFormat();
  const url = URL.createObjectURL(item.file);
  const video = document.createElement("video");
  video.playsInline = true;
  video.preload = "auto";
  video.crossOrigin = "anonymous";
  // Must be unmuted only when routed into WebAudio destination (so it doesn't play aloud to speakers!)
  video.muted = !exportConfig.videoKeepAudio;
  video.src = url;

  let audioCtx = null;
  let recorder = null;
  let rafId = null;

  try {
    await waitForEvent(video, "loadedmetadata");
    const origW = video.videoWidth;
    const origH = video.videoHeight;
    const duration = Number.isFinite(video.duration) && video.duration > 0 ? video.duration : 0;

    // Even dimensions for clean video encoding
    const outW = Math.max(2, origW - (origW % 2));
    const outH = Math.max(2, origH - (origH % 2));

    const canvas = document.createElement("canvas");
    canvas.width = outW;
    canvas.height = outH;
    const ctx = canvas.getContext("2d");

    // Pre-render one full-resolution transparent watermark overlay for maximum FPS!
    const overlayCanvas = buildOverlayCanvas(outW, outH, config, renderOpts);

    const canvasStream = canvas.captureStream(30);
    const tracks = [...canvasStream.getVideoTracks()];

    // Route video audio silently into the MediaStream without playing through user's speakers
    if (exportConfig.videoKeepAudio) {
      try {
        const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
        if (AudioContextCtor) {
          audioCtx = new AudioContextCtor();
          const sourceNode = audioCtx.createMediaElementSource(video);
          const destNode = audioCtx.createMediaStreamDestination();
          sourceNode.connect(destNode);
          // Do NOT connect to audioCtx.destination so export runs silently
          for (const at of destNode.stream.getAudioTracks()) {
            tracks.push(at);
          }
        }
      } catch {
        video.muted = true;
      }
    }

    const combinedStream = new MediaStream(tracks);
    const qualityFactor = Math.max(0.5, Math.min(1.0, (exportConfig.quality || 92) / 100));
    const pixels = outW * outH;
    const videoBitsPerSecond = Math.round(
      Math.max(1_500_000, Math.min(14_000_000, pixels * 4.5 * qualityFactor)),
    );

    const recOpts = { videoBitsPerSecond };
    if (mimeType) recOpts.mimeType = mimeType;
    recorder = new MediaRecorder(combinedStream, recOpts);

    const chunks = [];
    recorder.ondataavailable = (ev) => {
      if (ev.data && ev.data.size > 0) chunks.push(ev.data);
    };

    const stoppedPromise = new Promise((resolve, reject) => {
      recorder.onstop = () => resolve();
      recorder.onerror = (ev) => reject(ev.error || new Error("视频录制编码失败"));
    });

    const drawCurrentFrame = () => {
      ctx.drawImage(video, 0, 0, outW, outH);
      ctx.drawImage(overlayCanvas, 0, 0);
    };

    // Draw initial frame before starting recorder
    if (video.readyState < 2) {
      await waitForEvent(video, "loadeddata");
    }
    drawCurrentFrame();

    if (audioCtx && audioCtx.state === "suspended") {
      try {
        await audioCtx.resume();
      } catch {
        // ignore
      }
    }

    recorder.start(250);
    await video.play();

    let cancelled = false;
    await new Promise((resolve, reject) => {
      const tick = () => {
        if (isCancelled && isCancelled()) {
          cancelled = true;
          video.pause();
          resolve();
          return;
        }
        drawCurrentFrame();
        if (onProgress && duration > 0) {
          onProgress(Math.min(0.99, video.currentTime / duration));
        }
        if (video.ended) {
          resolve();
          return;
        }
        if (typeof video.requestVideoFrameCallback === "function") {
          video.requestVideoFrameCallback(tick);
        } else {
          rafId = requestAnimationFrame(tick);
        }
      };

      video.addEventListener("ended", () => {
        drawCurrentFrame();
        resolve();
      }, { once: true });

      video.addEventListener("error", () => {
        reject(new Error("视频播放解码中断"));
      }, { once: true });

      tick();
    });

    if (rafId) cancelAnimationFrame(rafId);
    if (recorder.state !== "inactive") {
      recorder.stop();
    }
    await stoppedPromise;

    if (cancelled) {
      throw new Error("__CANCELLED__");
    }

    if (onProgress) onProgress(1.0);
    const outBlob = new Blob(chunks, { type: mimeType || "video/webm" });
    return { blob: outBlob, ext };
  } finally {
    if (rafId) cancelAnimationFrame(rafId);
    try {
      video.pause();
      video.removeAttribute("src");
      video.load();
    } catch {
      // ignore
    }
    if (audioCtx) {
      try {
        await audioCtx.close();
      } catch {
        // ignore
      }
    }
    URL.revokeObjectURL(url);
  }
}
