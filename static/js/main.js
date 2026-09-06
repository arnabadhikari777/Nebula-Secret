/* ============================================================
   NEBULA SECRET — Frontend Logic (Vanilla JS, no frameworks)
   ============================================================ */

document.addEventListener("DOMContentLoaded", () => {

    /* ---------------- Tab Switching ---------------- */

    const tabButtons = document.querySelectorAll(".tab-btn");
    const tabPanels = document.querySelectorAll(".tab-panel");

    tabButtons.forEach((btn) => {
        btn.addEventListener("click", () => {
            const target = btn.dataset.tab;

            tabButtons.forEach((b) => {
                b.classList.remove("active");
                b.setAttribute("aria-selected", "false");
            });
            btn.classList.add("active");
            btn.setAttribute("aria-selected", "true");

            tabPanels.forEach((panel) => {
                panel.classList.toggle("active", panel.id === `panel-${target}`);
            });
        });
    });

    /* ---------------- Reusable Dropzone Wiring ---------------- */

    /**
     * Wires up drag-and-drop + click-to-browse behavior for a dropzone,
     * and shows an image preview once a file is selected.
     */
    function setupDropzone({ dropzoneId, inputId, contentId, previewId, previewImgId, filenameId }) {
        const dropzone = document.getElementById(dropzoneId);
        const input = document.getElementById(inputId);
        const content = document.getElementById(contentId);
        const preview = document.getElementById(previewId);
        const previewImg = document.getElementById(previewImgId);
        const filenameEl = document.getElementById(filenameId);

        function showPreview(file) {
            const reader = new FileReader();
            reader.onload = (e) => {
                previewImg.src = e.target.result;
                filenameEl.textContent = `${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
                content.hidden = true;
                preview.hidden = false;
            };
            reader.readAsDataURL(file);
        }

        dropzone.addEventListener("click", () => input.click());

        input.addEventListener("change", () => {
            if (input.files.length > 0) showPreview(input.files[0]);
        });

        ["dragenter", "dragover"].forEach((evt) => {
            dropzone.addEventListener(evt, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.add("dragover");
            });
        });

        ["dragleave", "drop"].forEach((evt) => {
            dropzone.addEventListener(evt, (e) => {
                e.preventDefault();
                e.stopPropagation();
                dropzone.classList.remove("dragover");
            });
        });

        dropzone.addEventListener("drop", (e) => {
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                input.files = files;
                showPreview(files[0]);
            }
        });
    }

    setupDropzone({
        dropzoneId: "encodeDropzone", inputId: "encodeFileInput",
        contentId: "encodeDropzoneContent", previewId: "encodePreview",
        previewImgId: "encodePreviewImg", filenameId: "encodeFilename",
    });

    setupDropzone({
        dropzoneId: "decodeDropzone", inputId: "decodeFileInput",
        contentId: "decodeDropzoneContent", previewId: "decodePreview",
        previewImgId: "decodePreviewImg", filenameId: "decodeFilename",
    });

    setupDropzone({
        dropzoneId: "exifDropzone", inputId: "exifFileInput",
        contentId: "exifDropzoneContent", previewId: "exifPreview",
        previewImgId: "exifPreviewImg", filenameId: "exifFilename",
    });

    /* ---------------- Status Box Helper ---------------- */

    function setStatus(el, type, message) {
        el.hidden = false;
        el.className = `status-box status-${type}`;
        el.textContent = message;
    }

    function clearStatus(el) {
        el.hidden = true;
        el.textContent = "";
    }

    /* ---------------- ENCODE FORM ---------------- */

    const encodeForm = document.getElementById("encodeForm");
    const encodeStatus = document.getElementById("encodeStatus");
    const encodeSubmitBtn = document.getElementById("encodeSubmitBtn");

    encodeForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        clearStatus(encodeStatus);

        const fileInput = document.getElementById("encodeFileInput");
        const message = document.getElementById("secretMessage").value.trim();

        if (!fileInput.files.length) {
            setStatus(encodeStatus, "error", "Please select an image to encode.");
            return;
        }
        if (!message) {
            setStatus(encodeStatus, "error", "Please enter a secret message.");
            return;
        }

        const formData = new FormData();
        formData.append("image", fileInput.files[0]);
        formData.append("message", message);

        encodeSubmitBtn.disabled = true;
        setStatus(encodeStatus, "loading", "🌌 Embedding your message into the pixel data...");

        try {
            const response = await fetch("/api/encode", { method: "POST", body: formData });

            if (response.ok && response.headers.get("Content-Type")?.includes("image")) {
                // Successful binary PNG response — trigger a download.
                const blob = await response.blob();
                const downloadUrl = window.URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = downloadUrl;

                const disposition = response.headers.get("Content-Disposition") || "";
                const match = disposition.match(/filename="?([^"]+)"?/);
                a.download = match ? match[1] : "nebula_encoded.png";

                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(downloadUrl);

                setStatus(encodeStatus, "success", "✅ Message encoded successfully! Your download has started.");
            } else {
                const data = await response.json();
                setStatus(encodeStatus, "error", `⚠️ ${data.error || "Encoding failed."}`);
            }
        } catch (err) {
            setStatus(encodeStatus, "error", "⚠️ Network error — could not reach the server.");
        } finally {
            encodeSubmitBtn.disabled = false;
        }
    });

    /* ---------------- DECODE FORM ---------------- */

    const decodeForm = document.getElementById("decodeForm");
    const decodeStatus = document.getElementById("decodeStatus");
    const decodeResult = document.getElementById("decodeResult");
    const decodeResultText = document.getElementById("decodeResultText");
    const decodeSubmitBtn = document.getElementById("decodeSubmitBtn");

    decodeForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        clearStatus(decodeStatus);
        decodeResult.hidden = true;

        const fileInput = document.getElementById("decodeFileInput");
        if (!fileInput.files.length) {
            setStatus(decodeStatus, "error", "Please select an image to decode.");
            return;
        }

        const formData = new FormData();
        formData.append("image", fileInput.files[0]);

        decodeSubmitBtn.disabled = true;
        setStatus(decodeStatus, "loading", "🔎 Scanning pixel data for hidden bits...");

        try {
            const response = await fetch("/api/decode", { method: "POST", body: formData });
            const data = await response.json();

            if (data.success) {
                clearStatus(decodeStatus);
                decodeResultText.textContent = data.message;
                decodeResult.hidden = false;
            } else {
                setStatus(decodeStatus, "warning", `⚠️ ${data.error}`);
            }
        } catch (err) {
            setStatus(decodeStatus, "error", "⚠️ Network error — could not reach the server.");
        } finally {
            decodeSubmitBtn.disabled = false;
        }
    });

    /* ---------------- EXIF FORM ---------------- */

    const exifForm = document.getElementById("exifForm");
    const exifStatus = document.getElementById("exifStatus");
    const exifResult = document.getElementById("exifResult");
    const exifResultLabel = document.getElementById("exifResultLabel");
    const exifTableBody = document.getElementById("exifTableBody");
    const exifSubmitBtn = document.getElementById("exifSubmitBtn");

    exifForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        clearStatus(exifStatus);
        exifResult.hidden = true;
        exifTableBody.innerHTML = "";

        const fileInput = document.getElementById("exifFileInput");
        if (!fileInput.files.length) {
            setStatus(exifStatus, "error", "Please select an image to inspect.");
            return;
        }

        const formData = new FormData();
        formData.append("image", fileInput.files[0]);

        exifSubmitBtn.disabled = true;
        setStatus(exifStatus, "loading", "🛰️ Extracting metadata from the image...");

        try {
            const response = await fetch("/api/exif", { method: "POST", body: formData });
            const data = await response.json();

            if (!data.success) {
                setStatus(exifStatus, "error", `⚠️ ${data.error}`);
                return;
            }

            clearStatus(exifStatus);

            // Always show basic file info first.
            const rows = [];
            for (const [key, value] of Object.entries(data.basic_info || {})) {
                rows.push({ key, value });
            }

            if (data.has_exif) {
                for (const [key, value] of Object.entries(data.metadata)) {
                    rows.push({ key, value });
                }
                exifResultLabel.textContent = "Metadata Report";
            } else {
                exifResultLabel.textContent = "Basic Image Info (No EXIF Found)";
            }

            rows.forEach(({ key, value }) => {
                const tr = document.createElement("tr");

                const keyTd = document.createElement("td");
                keyTd.className = "exif-key";
                keyTd.textContent = key;

                const valTd = document.createElement("td");
                if (key === "GPS Maps Link") {
                    const a = document.createElement("a");
                    a.href = value;
                    a.target = "_blank";
                    a.rel = "noopener noreferrer";
                    a.textContent = "View on Google Maps ↗";
                    valTd.appendChild(a);
                } else {
                    valTd.textContent = String(value);
                }

                tr.appendChild(keyTd);
                tr.appendChild(valTd);
                exifTableBody.appendChild(tr);
            });

            if (!data.has_exif && data.message) {
                setStatus(exifStatus, "warning", `ℹ️ ${data.message}`);
            }

            exifResult.hidden = false;
        } catch (err) {
            setStatus(exifStatus, "error", "⚠️ Network error — could not reach the server.");
        } finally {
            exifSubmitBtn.disabled = false;
        }
    });

});
