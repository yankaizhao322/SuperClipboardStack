(() => {
  const imageInput = document.getElementById("imageInput");
  const canvas = document.getElementById("previewCanvas");
  const applyCropBtn = document.getElementById("applyCropBtn");
  const clearImageBtn = document.getElementById("clearImageBtn");
  const hiddenInput = document.getElementById("croppedImageData");
  const keepExistingInput = document.getElementById("keepExistingImage");

  if (!imageInput || !canvas || !applyCropBtn || !clearImageBtn || !hiddenInput) {
    return;
  }

  const ctx = canvas.getContext("2d");
  const img = new Image();
  let hasImage = false;

  const selection = {
    x: 20,
    y: 20,
    w: 100,
    h: 100,
    dragging: false,
    startX: 0,
    startY: 0,
  };

  function clearCanvas() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#f6f8fb";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#6b7280";
    ctx.font = "14px Segoe UI";
    ctx.fillText("上传图片后可框选裁剪区域", 14, 24);
  }

  function draw() {
    clearCanvas();
    if (!hasImage) return;

    const ratio = Math.min(canvas.width / img.width, canvas.height / img.height);
    const drawW = img.width * ratio;
    const drawH = img.height * ratio;
    const drawX = (canvas.width - drawW) / 2;
    const drawY = (canvas.height - drawH) / 2;

    ctx.drawImage(img, drawX, drawY, drawW, drawH);
    ctx.strokeStyle = "#2b6ef3";
    ctx.lineWidth = 2;
    ctx.strokeRect(selection.x, selection.y, selection.w, selection.h);
    ctx.fillStyle = "rgba(43,110,243,0.12)";
    ctx.fillRect(selection.x, selection.y, selection.w, selection.h);
  }

  function clampSelection() {
    selection.x = Math.max(0, Math.min(selection.x, canvas.width - selection.w));
    selection.y = Math.max(0, Math.min(selection.y, canvas.height - selection.h));
    selection.w = Math.max(20, Math.min(selection.w, canvas.width - selection.x));
    selection.h = Math.max(20, Math.min(selection.h, canvas.height - selection.y));
  }

  function pointerPos(evt) {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return {
      x: (evt.clientX - rect.left) * scaleX,
      y: (evt.clientY - rect.top) * scaleY,
    };
  }

  canvas.addEventListener("mousedown", (evt) => {
    if (!hasImage) return;
    const p = pointerPos(evt);
    selection.dragging = true;
    selection.startX = p.x;
    selection.startY = p.y;
    selection.x = p.x;
    selection.y = p.y;
    selection.w = 1;
    selection.h = 1;
    draw();
  });

  canvas.addEventListener("mousemove", (evt) => {
    if (!selection.dragging || !hasImage) return;
    const p = pointerPos(evt);
    selection.x = Math.min(selection.startX, p.x);
    selection.y = Math.min(selection.startY, p.y);
    selection.w = Math.abs(p.x - selection.startX);
    selection.h = Math.abs(p.y - selection.startY);
    clampSelection();
    draw();
  });

  canvas.addEventListener("mouseup", () => {
    selection.dragging = false;
  });

  canvas.addEventListener("mouseleave", () => {
    selection.dragging = false;
  });

  imageInput.addEventListener("change", () => {
    const [file] = imageInput.files;
    if (!file) return;

    const reader = new FileReader();
    reader.onload = () => {
      img.onload = () => {
        hasImage = true;
        selection.x = 30;
        selection.y = 30;
        selection.w = Math.max(60, canvas.width / 2);
        selection.h = Math.max(60, canvas.height / 2);
        hiddenInput.value = "";
        if (keepExistingInput) keepExistingInput.value = "0";
        draw();
      };
      img.src = String(reader.result);
    };
    reader.readAsDataURL(file);
  });

  applyCropBtn.addEventListener("click", () => {
    if (!hasImage) return;
    clampSelection();

    const output = document.createElement("canvas");
    output.width = Math.floor(selection.w);
    output.height = Math.floor(selection.h);
    const octx = output.getContext("2d");

    const ratio = Math.min(canvas.width / img.width, canvas.height / img.height);
    const drawW = img.width * ratio;
    const drawH = img.height * ratio;
    const drawX = (canvas.width - drawW) / 2;
    const drawY = (canvas.height - drawH) / 2;

    const sx = ((selection.x - drawX) / drawW) * img.width;
    const sy = ((selection.y - drawY) / drawH) * img.height;
    const sw = (selection.w / drawW) * img.width;
    const sh = (selection.h / drawH) * img.height;

    octx.drawImage(img, sx, sy, sw, sh, 0, 0, output.width, output.height);
    hiddenInput.value = output.toDataURL("image/png");

    img.onload = () => {
      draw();
    };
    img.src = hiddenInput.value;

    if (keepExistingInput) keepExistingInput.value = "0";
  });

  clearImageBtn.addEventListener("click", () => {
    imageInput.value = "";
    hiddenInput.value = "";
    hasImage = false;
    if (keepExistingInput && !window.__isEditPage) {
      keepExistingInput.value = "0";
    }
    if (keepExistingInput && window.__isEditPage) {
      keepExistingInput.value = "1";
    }
    clearCanvas();
  });

  clearCanvas();
})();
