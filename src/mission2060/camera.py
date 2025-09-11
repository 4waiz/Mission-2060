from __future__ import annotations
from typing import List
import numpy as np
import cv2

from bosdyn.client.image import ImageClient, build_image_request
from bosdyn.api import image_pb2

# Common sources on Spot:
DEFAULT_SOURCES = [
    "frontleft_fisheye_image",
    "frontright_fisheye_image",
    "left_fisheye_image",
    "right_fisheye_image",
    "back_fisheye_image",
]

def list_sources(image_client: ImageClient) -> List[str]:
    """Ask Spot which image sources exist."""
    return [src.name for src in image_client.list_image_sources()]  # documented in Image client. :contentReference[oaicite:18]{index=18}

def fetch_bgr(image_client: ImageClient, source: str = "frontleft_fisheye_image", jpeg_quality: int = 80) -> np.ndarray:
    try: 
        req = build_image_request( 
            image_source_name=source, 
            image_format=image_pb2.Image.FORMAT_JPEG, 
            quality_percent=jpeg_quality, 
        )
    except TypeError:
        # Older signature: first arg is the source name positionally. 
        req = build_image_request( 
            source, 
            image_format=image_pb2.Image.FORMAT_JPEG, 
            quality_percent=jpeg_quality, 
        )
    resp = image_client.get_image([req])[0]
    # JPEG decode to BGR
    img = np.frombuffer(resp.shot.image.data, dtype=np.uint8)
    bgr = cv2.imdecode(img, cv2.IMREAD_COLOR)
    return bgr
