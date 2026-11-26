// Images to attach to a message: a frame of the screen (a window the person picks) or a file.

export const canCaptureScreen = () => !!navigator.mediaDevices?.getDisplayMedia;

/** One frame of a screen, window or tab the user picks (the browser asks every time). */
export async function screenPNG() {
  if (!canCaptureScreen()) throw new Error('This browser cannot capture the screen');
  const stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
  try {
    const video = document.createElement('video');
    video.muted = true; video.playsInline = true; video.srcObject = stream;
    await video.play();
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const scale = Math.min(1, 2400 / video.videoWidth);
    return toPNG(video, video.videoWidth, video.videoHeight, scale);
  } finally { for (const t of stream.getTracks()) t.stop(); }
}

/** A picked or pasted image file, scaled down if huge. */
export async function filePNG(file) {
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    await new Promise((ok, bad) => { img.onload = ok; img.onerror = () => bad(new Error('Not an image')); img.src = url; });
    return toPNG(img, img.naturalWidth, img.naturalHeight, Math.min(1, 2400 / Math.max(img.naturalWidth, img.naturalHeight)));
  } finally { URL.revokeObjectURL(url); }
}

function toPNG(src, w, h, scale) {
  const cv = document.createElement('canvas');
  cv.width = Math.round(w * scale); cv.height = Math.round(h * scale);
  cv.getContext('2d').drawImage(src, 0, 0, cv.width, cv.height);
  return cv.toDataURL('image/png');
}
