#!/usr/bin/env python3
"""
Meshy Image to 3D — モンスター画像 → 3Dモデル変換
Usage:
  python3 meshy_img2mesh.py --image /tmp/monster_fire_cat.png --name fire_cat
  python3 meshy_img2mesh.py --image /tmp/monster_fire_cat.png --name fire_cat --test  # テストモード
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.request
import urllib.error

API_BASE = "https://api.meshy.ai"
TEST_API_KEY = "msy_test_api_key_for_development_only"


def get_api_key(test_mode=False):
    if test_mode:
        return TEST_API_KEY
    key = os.environ.get("MESHY_API_KEY")
    if key:
        return key
    # Check openclaw config
    config_path = os.path.expanduser("~/.openclaw/openclaw.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            cfg = json.load(f)
        key = (cfg.get("skills", {}).get("entries", {})
               .get("meshy", {}).get("env", {})
               .get("MESHY_API_KEY"))
        if key:
            return key
    raise RuntimeError("MESHY_API_KEY not found. Set env var or use --test mode.")


def create_task(api_key: str, image_path: str, ai_model: str = "meshy-6",
                topology: str = "triangle", target_polycount: int = 10000) -> str:
    """Create Image to 3D task, returns task ID."""
    # Encode image as data URI
    ext = os.path.splitext(image_path)[1].lower()
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(ext.lstrip("."), "image/png")
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    data_uri = f"data:{mime};base64,{b64}"

    body = {
        "image_url": data_uri,
        "ai_model": ai_model,
        "topology": topology,
        "target_polycount": target_polycount,
        "enable_pbr": True,
        "should_remesh": True,
    }

    req = urllib.request.Request(
        f"{API_BASE}/openapi/v1/image-to-3d",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    resp = urllib.request.urlopen(req, timeout=30)
    result = json.loads(resp.read())
    task_id = result.get("result")
    print(f"✅ Task created: {task_id}")
    return task_id


def poll_task(api_key: str, task_id: str, interval: int = 10, timeout: int = 600) -> dict:
    """Poll task until complete."""
    start = time.time()
    while time.time() - start < timeout:
        req = urllib.request.Request(
            f"{API_BASE}/openapi/v1/image-to-3d/{task_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp = urllib.request.urlopen(req, timeout=30)
        task = json.loads(resp.read())
        status = task.get("status", "")
        progress = task.get("progress", 0)
        print(f"  [{status}] {progress}%", end="\r")

        if status == "SUCCEEDED":
            print(f"\n🎉 Complete!")
            return task
        elif status == "FAILED":
            print(f"\n❌ Failed: {task.get('task_error', {}).get('message', 'unknown')}")
            return task
        elif status == "EXPIRED":
            print(f"\n⏰ Expired")
            return task

        time.sleep(interval)

    print("\n⏰ Timeout")
    return {}


def download_model(task: dict, output_dir: str, name: str):
    """Download GLB model from completed task."""
    os.makedirs(output_dir, exist_ok=True)
    model_urls = task.get("model_urls", {})

    for fmt, url in model_urls.items():
        if not url:
            continue
        ext = fmt.lower()
        out_path = os.path.join(output_dir, f"{name}.{ext}")
        print(f"📥 Downloading {fmt} → {out_path}")
        urllib.request.urlretrieve(url, out_path)
        print(f"   Saved: {out_path} ({os.path.getsize(out_path)} bytes)")

    # Also save thumbnail
    thumbnail = task.get("thumbnail_url")
    if thumbnail:
        thumb_path = os.path.join(output_dir, f"{name}_thumb.png")
        urllib.request.urlretrieve(thumbnail, thumb_path)
        print(f"🖼️ Thumbnail: {thumb_path}")

    return output_dir


def main():
    parser = argparse.ArgumentParser(description="Meshy Image to 3D")
    parser.add_argument("--image", help="Input image path")
    parser.add_argument("--name", default="monster", help="Output name prefix")
    parser.add_argument("--output", default="/tmp/meshy_models", help="Output directory")
    parser.add_argument("--test", action="store_true", help="Use test API key")
    parser.add_argument("--ai-model", default="meshy-6", help="AI model (meshy-5, meshy-6)")
    parser.add_argument("--polycount", type=int, default=10000, help="Target polycount")
    parser.add_argument("--task-id", help="Resume polling existing task")
    args = parser.parse_args()

    api_key = get_api_key(args.test)
    print(f"🔑 Mode: {'TEST' if args.test else 'PRODUCTION'}")

    if args.task_id:
        task_id = args.task_id
    else:
        print(f"📸 Image: {args.image}")
        task_id = create_task(api_key, args.image, args.ai_model, "triangle", args.polycount)

    print(f"⏳ Polling task {task_id}...")
    task = poll_task(api_key, task_id)

    if task.get("status") == "SUCCEEDED":
        download_model(task, args.output, args.name)
        print(f"\n✨ Done! Models saved to {args.output}/{args.name}.*")
        # Print model URLs for reference
        print(f"\nModel URLs:")
        for fmt, url in task.get("model_urls", {}).items():
            if url:
                print(f"  {fmt}: {url}")
    else:
        print(json.dumps(task, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
