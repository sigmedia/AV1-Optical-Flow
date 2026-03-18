"""
 utils.py

  Created by Julien Zouein on 18/03/2026.
  Copyright © 2026 Sigmedia.tv. All rights reserved.
  Copyright © 2026 Julien Zouein (zoueinj@tcd.ie)
----------------------------------------------------------------------------

 Python file used to define all the utility functions.
"""

import cv2
import numpy as np


def upscale(method: str, frame: np.ndarray, MiSize: int = 4) -> np.ndarray:
    """Upscale motion field to frame size.

    The motion field extracted from the JSON file does not have the same
    resolution as the frame. The shape of the motion field is:
        - width: (frame_width / MiSize)
        - height: (frame_height / MiSize)
        - channels: 4

    MiSize is ususally 4 (smallest block supported by AV1).

    Args:
        method (str): Method to use for upscaling.
        frame (np.array): Frame to upscale.
        MiSize (int): MiSize to use for upscaling.

    Returns:
        np.array: Upscaled frame.
    """

    methods = {
        "bicubic": cv2.INTER_CUBIC,
        "nearest": cv2.INTER_NEAREST,
        "bilinear": cv2.INTER_LINEAR,
        "area": cv2.INTER_AREA,
        "lanczos": cv2.INTER_LANCZOS4,
    }

    if method not in methods:
        return frame

    else:
        return cv2.resize(
            frame,
            (frame.shape[1] * MiSize, frame.shape[0] * MiSize),
            interpolation=methods[method],
        )
