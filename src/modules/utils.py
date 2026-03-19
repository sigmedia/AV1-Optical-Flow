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


def bidirectional_filling(
    motion_backward: np.ndarray, motion_forward: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Bidirectional filling of the motion field.

    This function is used to fill the blocks without motion vectors.
    Video encoders associate a motion vector to predicted blocks. Some
    blocks are "intra blocks" and do not have a motion vector in a
    specific direction. Bidirectional filling is used to fill the motion
    vectors for these blocks by taking the motion vector from the other direction.

    Args:
        motion_backward (np.ndarray): Backward motion field.
        motion_forward (np.ndarray): Forward motion field.

    Returns:
        tuple: Two numpy arrays containing the backward and forward motion vectors.
    """

    result_backward = motion_backward.copy()
    result_forward = motion_forward.copy()

    # Create masks for zero vectors
    backward_zero = (result_backward[..., 0] == 0) & (result_backward[..., 1] == 0)
    forward_zero = (result_forward[..., 0] == 0) & (result_forward[..., 1] == 0)

    # Update where backward is zero
    result_backward[backward_zero, 0] = -result_forward[backward_zero, 0]
    result_backward[backward_zero, 1] = -result_forward[backward_zero, 1]

    # Update where forward is zero
    result_forward[forward_zero, 0] = -result_backward[forward_zero, 0]
    result_forward[forward_zero, 1] = -result_backward[forward_zero, 1]

    return result_backward, result_forward


def check_ivf_file(file_path: str) -> bool:
    """Check if the file is an IVF file.

    Args:
        file_path (str): Path to the file.

    Returns:
        bool: True if the file is an IVF file, False otherwise.
    """

    IVF_SIGNATURE = b"DKIF"
    IVF_HEADER_SIZE = 32
    CODEC = b"AV01"

    with open(file_path, "rb") as file:
        header = file.read(IVF_HEADER_SIZE)

        signature = header[:4]
        codec = header[8:12]

        if signature != IVF_SIGNATURE or codec != CODEC:
            return False
        return True


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
