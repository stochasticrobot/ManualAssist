"""Check whether the configured text and image models can answer simple requests.

This developer command helps distinguish a connection problem from a problem in
manual analysis. Its default mode only describes the checks. With --live it sends
two small requests, saves their replies and checks the expected answers; those
requests may incur provider charges."""

import argparse
from dataclasses import asdict
from io import BytesIO
import json
from datetime import datetime, timezone
from PIL import Image as PILImage, ImageDraw, ImageFont
from workbench.config import ROOT
from workbench.model_access.configure_model_providers import configured_service
from workbench.model_access.model_requests_and_responses import Image, Request
from workbench.model_access.parse_model_json import read_json


def run() -> None:
    """Run two bounded live calls only when explicitly requested.

    Args:
        None. Reads --live from CLI; loads private configuration through the adapter.
    Returns:
        None; saves a receipt and exits nonzero if either expected answer is wrong.
        With --live, makes at most two paid calls and saves the synthetic test image.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        print(
            "Preview: two calls through ModelService: text READY and inside/outside word image. Use --live."
        )
        return
    service = configured_service()
    dest = ROOT / "data" / "verification"
    dest.mkdir(parents=True, exist_ok=True)
    image = PILImage.new("RGB", (600, 360), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
    draw.rectangle((100, 110, 500, 310), outline="black", width=5)
    draw.text((220, 190), "MAPLE", fill="black", font=font)
    draw.text((220, 30), "RIVER", fill="black", font=font)
    buf = BytesIO()
    image.save(buf, format="PNG")
    (dest / "inside-outside.png").write_bytes(buf.getvalue())
    text_result = service.generate(
        "text",
        Request(
            "Reply with exactly these five ASCII characters and nothing else, with no punctuation: READY",
            max_tokens=64,
        ),
    )
    vision_result = service.generate(
        "vision",
        Request(
            "Identify the word inside the rectangle and the word outside it. Reply only JSON with keys inside and outside.",
            images=(Image(buf.getvalue()),),
            max_tokens=128,
        ),
    )
    try:
        answer = read_json(vision_result.text)
    except ValueError:
        answer = {}
    passed = text_result.text.strip() == "READY" and answer == {
        "inside": "MAPLE",
        "outside": "RIVER",
    }
    receipt = {
        "passed": passed,
        "entry_point": "ModelService.generate",
        "text": asdict(text_result),
        "vision": asdict(vision_result),
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    (dest / f"live-smoke-{stamp}.json").write_text(json.dumps(receipt, indent=2))
    (dest / "live-smoke.json").write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    run()
