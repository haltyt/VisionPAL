"""
SHARP Server — REST API for single-image → 3DGS generation
Runs on PC with CUDA, receives JPEG from JetBot/VisionPAL, returns .ply

Usage:
    conda activate sharp
    python sharp_server.py --port 8080

Endpoints:
    POST /generate     — JPEG body → .ply response
    GET  /health       — Server status
    GET  /last         — Download last generated .ply
"""

import argparse
import io
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Config
SHARP_DIR = Path(r"D:\ml-sharp")
OUTPUT_DIR = Path(tempfile.gettempdir()) / "sharp_output"
OUTPUT_DIR.mkdir(exist_ok=True)

last_ply_path: Path | None = None
generation_count = 0
start_time = time.time()


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "sharp_dir": str(SHARP_DIR),
        "cuda_available": True,  # Assume CUDA if server started
        "generations": generation_count,
        "uptime_seconds": int(time.time() - start_time),
        "last_ply": str(last_ply_path) if last_ply_path else None,
    })


@app.route("/generate", methods=["POST"])
def generate():
    """Receive JPEG image, run SHARP, return .ply"""
    global last_ply_path, generation_count

    # Accept image from body or multipart
    if request.content_type and "multipart" in request.content_type:
        file = request.files.get("image")
        if not file:
            return jsonify({"error": "No 'image' file in multipart"}), 400
        image_data = file.read()
    else:
        image_data = request.get_data()

    if not image_data or len(image_data) < 100:
        return jsonify({"error": "No image data received"}), 400

    # Save input image
    timestamp = int(time.time())
    input_path = OUTPUT_DIR / f"input_{timestamp}.jpg"
    output_path = OUTPUT_DIR / f"output_{timestamp}.ply"

    input_path.write_bytes(image_data)
    print(f"[SHARP] Received {len(image_data)} bytes, saving to {input_path}")

    # Run SHARP inference
    t0 = time.time()
    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "sharp.infer",
                "--input", str(input_path),
                "--output", str(output_path),
                "--device", "cuda",
            ],
            cwd=str(SHARP_DIR),
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            print(f"[SHARP] Error: {result.stderr}")
            return jsonify({
                "error": "SHARP inference failed",
                "stderr": result.stderr[-500:] if result.stderr else "",
            }), 500

    except subprocess.TimeoutExpired:
        return jsonify({"error": "SHARP inference timed out (60s)"}), 504
    except FileNotFoundError:
        return jsonify({"error": "SHARP not found. Check SHARP_DIR config."}), 500

    elapsed = time.time() - t0

    if not output_path.exists():
        return jsonify({"error": "SHARP produced no output"}), 500

    ply_size = output_path.stat().st_size
    last_ply_path = output_path
    generation_count += 1

    print(f"[SHARP] Generated {ply_size} bytes in {elapsed:.1f}s")

    return send_file(
        output_path,
        mimetype="application/x-ply",
        as_attachment=True,
        download_name=f"scan_{timestamp}.ply",
    )


@app.route("/last", methods=["GET"])
def last():
    """Download the last generated .ply"""
    if last_ply_path and last_ply_path.exists():
        return send_file(last_ply_path, mimetype="application/x-ply")
    return jsonify({"error": "No .ply generated yet"}), 404


@app.route("/generate_preview", methods=["POST"])
def generate_preview():
    """Same as /generate but also returns a preview thumbnail (for UI)"""
    # TODO: Generate a 2D preview render alongside the .ply
    return generate()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SHARP 3DGS Server")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--sharp-dir", type=str, default=str(SHARP_DIR))
    args = parser.parse_args()

    SHARP_DIR = Path(args.sharp_dir)
    print(f"[SHARP Server] Starting on {args.host}:{args.port}")
    print(f"[SHARP Server] SHARP dir: {SHARP_DIR}")
    print(f"[SHARP Server] Output dir: {OUTPUT_DIR}")

    app.run(host=args.host, port=args.port, debug=False)
