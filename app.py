"""
Nebula Secret — Secure Steganography & Image Forensics Suite
=============================================================
A stateless Flask application that performs:
    1. LSB (Least Significant Bit) image steganography (encode / decode)
    2. EXIF metadata extraction / forensics inspection

Design notes:
    - Everything is processed in-memory using io.BytesIO.
      No file is ever written to disk, which makes this safe to run on
      read-only / ephemeral filesystems such as Render's free tier.
    - Encoded images are always returned as PNG, since PNG is a lossless
      format and JPEG's lossy compression would destroy the hidden bits.

Author credit: Created by Arnab Adhikari
"""

import io
import base64
from datetime import datetime

from flask import Flask, render_template, request, send_file, jsonify
from PIL import Image, ExifTags
from PIL.ExifTags import GPSTAGS
from werkzeug.utils import secure_filename

app = Flask(__name__)

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB upload limit
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}

# Unique delimiter used to mark the end of the hidden message.
# Chosen to be extremely unlikely to appear naturally in plain text.
DELIMITER = "#####END#####"


# ----------------------------------------------------------------------------
# Helper Functions
# ----------------------------------------------------------------------------

def allowed_file(filename: str) -> bool:
    """Check whether the uploaded filename has an allowed image extension."""
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def text_to_binary(message: str) -> str:
    """Convert a UTF-8 text string into a continuous binary string."""
    return "".join(format(byte, "08b") for byte in message.encode("utf-8"))


def binary_to_text(binary_str: str) -> str:
    """Convert a binary string (multiple of 8 bits) back into UTF-8 text."""
    byte_chunks = [binary_str[i:i + 8] for i in range(0, len(binary_str), 8)]
    byte_values = bytearray(int(chunk, 2) for chunk in byte_chunks if len(chunk) == 8)
    return byte_values.decode("utf-8", errors="ignore")


def encode_lsb(image: Image.Image, secret_message: str) -> Image.Image:
    """
    Embed `secret_message` into the least significant bit of each color
    channel of `image`, appending a delimiter so the decoder knows where
    the hidden data ends.

    Raises:
        ValueError: if the image is too small to hold the message.
    """
    # Work on a copy converted to RGB so we have exactly 3 channels per pixel
    # (this also normalizes RGBA / palette images into a consistent mode).
    encoded_image = image.convert("RGB")
    width, height = encoded_image.size
    pixels = list(encoded_image.getdata())

    # Full payload = message bits + delimiter bits
    payload = text_to_binary(secret_message + DELIMITER)
    payload_length = len(payload)

    capacity_bits = width * height * 3  # 1 bit hideable per color channel
    if payload_length > capacity_bits:
        raise ValueError(
            "Message is too large for this image. "
            f"Capacity: {capacity_bits // 8} bytes, "
            f"required: {payload_length // 8} bytes. "
            "Use a larger image or a shorter message."
        )

    new_pixels = []
    bit_index = 0

    for pixel in pixels:
        r, g, b = pixel[0], pixel[1], pixel[2]

        if bit_index < payload_length:
            r = (r & ~1) | int(payload[bit_index])
            bit_index += 1
        if bit_index < payload_length:
            g = (g & ~1) | int(payload[bit_index])
            bit_index += 1
        if bit_index < payload_length:
            b = (b & ~1) | int(payload[bit_index])
            bit_index += 1

        new_pixels.append((r, g, b))

        # Once every bit has been embedded, stop touching pixels; keep the rest untouched.
        if bit_index >= payload_length and len(new_pixels) < len(pixels):
            new_pixels.extend(pixels[len(new_pixels):])
            break

    encoded_image.putdata(new_pixels)
    return encoded_image


def decode_lsb(image: Image.Image) -> str:
    """
    Extract a hidden message from `image` by reading the least significant
    bit of each color channel until the DELIMITER is found.

    Returns:
        The decoded secret message string, or "" if no delimiter is found.
    """
    decoded_image = image.convert("RGB")
    pixels = list(decoded_image.getdata())

    bits = []
    delimiter_bits = text_to_binary(DELIMITER)
    delimiter_len = len(delimiter_bits)

    for pixel in pixels:
        for channel_value in pixel[:3]:
            bits.append(str(channel_value & 1))

            # Periodically check the tail of the extracted bits against the
            # delimiter to allow early exit on large images.
            if len(bits) >= delimiter_len and len(bits) % 8 == 0:
                tail = "".join(bits[-delimiter_len:])
                if tail == delimiter_bits:
                    message_bits = "".join(bits[:-delimiter_len])
                    return binary_to_text(message_bits)

    # No delimiter found within the entire image — no hidden message present.
    return None


def convert_to_degrees(value):
    """Convert an EXIF GPS coordinate (degrees, minutes, seconds) to decimal degrees."""
    d, m, s = value[0], value[1], value[2]
    return float(d) + (float(m) / 60.0) + (float(s) / 3600.0)


def extract_exif(image: Image.Image) -> dict:
    """
    Extract human-readable EXIF metadata from a Pillow image, including
    a best-effort GPS coordinate conversion.

    Returns:
        A dict of {tag_name: value} for display in the UI. Empty dict if
        the image has no EXIF data at all.
    """
    exif_data = {}
    raw_exif = image.getexif()

    if not raw_exif:
        return exif_data

    gps_info = {}

    for tag_id, value in raw_exif.items():
        tag_name = ExifTags.TAGS.get(tag_id, tag_id)

        # The GPS IFD is nested under its own tag. raw_exif.items() only
        # yields an IFD pointer (an int) for GPSInfo, not the actual GPS
        # tag dictionary, so it must be resolved separately via get_ifd().
        if tag_name == "GPSInfo":
            continue

        # Skip binary blobs that aren't useful to display directly.
        if isinstance(value, bytes):
            try:
                value = value.decode("utf-8", errors="ignore").strip("\x00")
            except Exception:
                continue

        exif_data[str(tag_name)] = value

    # Resolve the nested GPS IFD (if present) into a proper tag dictionary.
    try:
        gps_ifd = raw_exif.get_ifd(ExifTags.IFD.GPSInfo)
        for gps_tag_id, gps_value in gps_ifd.items():
            gps_tag_name = GPSTAGS.get(gps_tag_id, gps_tag_id)
            gps_info[gps_tag_name] = gps_value
    except Exception:
        # No GPS IFD present, or it couldn't be parsed — skip silently.
        pass

    # Convert raw GPS rational values into a friendly decimal-degree string.
    if gps_info:
        try:
            lat = convert_to_degrees(gps_info["GPSLatitude"])
            if gps_info.get("GPSLatitudeRef") == "S":
                lat = -lat
            lon = convert_to_degrees(gps_info["GPSLongitude"])
            if gps_info.get("GPSLongitudeRef") == "W":
                lon = -lon
            exif_data["GPS Coordinates"] = f"{lat:.6f}, {lon:.6f}"
            exif_data["GPS Maps Link"] = f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"
        except (KeyError, TypeError, ZeroDivisionError):
            # Malformed or partial GPS data — skip rather than crash.
            pass

    return exif_data


# ----------------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------------

@app.route("/")
def index():
    """Render the single-page tabbed UI."""
    return render_template("index.html")


@app.route("/api/encode", methods=["POST"])
def api_encode():
    """
    Encode a secret message into an uploaded image and return the
    steganographic result as a downloadable PNG.
    """
    if "image" not in request.files:
        return jsonify({"success": False, "error": "No image file was uploaded."}), 400

    file = request.files["image"]
    secret_message = request.form.get("message", "").strip()

    if file.filename == "":
        return jsonify({"success": False, "error": "No file selected."}), 400

    if not allowed_file(file.filename):
        return jsonify({"success": False, "error": "Unsupported file type. Use PNG, JPG, or JPEG."}), 400

    if not secret_message:
        return jsonify({"success": False, "error": "Secret message cannot be empty."}), 400

    try:
        # Read upload directly into memory — never touches disk.
        input_bytes = io.BytesIO(file.read())
        source_image = Image.open(input_bytes)

        encoded_image = encode_lsb(source_image, secret_message)

        # Write the result to an in-memory buffer as lossless PNG.
        output_buffer = io.BytesIO()
        encoded_image.save(output_buffer, format="PNG")
        output_buffer.seek(0)

        original_name = secure_filename(file.filename).rsplit(".", 1)[0]
        download_name = f"{original_name}_nebula_encoded.png"

        return send_file(
            output_buffer,
            mimetype="image/png",
            as_attachment=True,
            download_name=download_name,
        )

    except ValueError as ve:
        return jsonify({"success": False, "error": str(ve)}), 400
    except Exception:
        return jsonify({"success": False, "error": "Failed to process the image. Please try a different file."}), 500


@app.route("/api/decode", methods=["POST"])
def api_decode():
    """Decode a hidden message from an uploaded steganographic image."""
    if "image" not in request.files:
        return jsonify({"success": False, "error": "No image file was uploaded."}), 400

    file = request.files["image"]

    if file.filename == "":
        return jsonify({"success": False, "error": "No file selected."}), 400

    if not allowed_file(file.filename):
        return jsonify({"success": False, "error": "Unsupported file type. Use PNG, JPG, or JPEG."}), 400

    try:
        input_bytes = io.BytesIO(file.read())
        image = Image.open(input_bytes)

        hidden_message = decode_lsb(image)

        if hidden_message is None or hidden_message == "":
            return jsonify({
                "success": False,
                "error": "No hidden message was found in this image. "
                         "It may not be steganographically encoded, or it was re-compressed (e.g. re-saved as JPEG), which destroys hidden data."
            }), 200

        return jsonify({"success": True, "message": hidden_message})

    except Exception:
        return jsonify({"success": False, "error": "Failed to read the image. Please upload a valid image file."}), 500


@app.route("/api/exif", methods=["POST"])
def api_exif():
    """Extract and return EXIF metadata from an uploaded image as JSON."""
    if "image" not in request.files:
        return jsonify({"success": False, "error": "No image file was uploaded."}), 400

    file = request.files["image"]

    if file.filename == "":
        return jsonify({"success": False, "error": "No file selected."}), 400

    if not allowed_file(file.filename):
        return jsonify({"success": False, "error": "Unsupported file type. Use PNG, JPG, or JPEG."}), 400

    try:
        input_bytes = io.BytesIO(file.read())
        image = Image.open(input_bytes)

        metadata = extract_exif(image)

        # Basic file/image info is always available, even without EXIF.
        basic_info = {
            "File Format": image.format,
            "Image Size": f"{image.size[0]} x {image.size[1]} px",
            "Color Mode": image.mode,
        }

        if not metadata:
            return jsonify({
                "success": True,
                "has_exif": False,
                "basic_info": basic_info,
                "metadata": {},
                "message": "No EXIF metadata found in this image. "
                           "It may have been stripped, generated synthetically, or the format doesn't support EXIF (e.g. some PNGs)."
            })

        return jsonify({
            "success": True,
            "has_exif": True,
            "basic_info": basic_info,
            "metadata": metadata,
        })

    except Exception:
        return jsonify({"success": False, "error": "Failed to read the image. Please upload a valid image file."}), 500


@app.errorhandler(413)
def file_too_large(_error):
    """Friendly error when the upload exceeds MAX_CONTENT_LENGTH."""
    return jsonify({"success": False, "error": "File too large. Maximum upload size is 16 MB."}), 413


if __name__ == "__main__":
    # Local development entry point. On Render, gunicorn serves `app:app` instead.
    app.run(debug=True, host="0.0.0.0", port=5000)
