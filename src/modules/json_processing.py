"""
 json_processing.py

  Created by Julien Zouein on 18/03/2026.
  Copyright © 2026 Sigmedia.tv. All rights reserved.
  Copyright © 2026 Julien Zouein (zoueinj@tcd.ie)
----------------------------------------------------------------------------

 AOM inspect tool is used to retrieve metadata out of AV1 files. This tool save
 the matadata in a JSON file.
 In this file, we define all the functions to process the JSON file.
"""

import numpy as np

from .utils import bidirectional_filling
from .utils import upscale


def get_motion_vectors(
    frame_data: dict,
    frame_number: int,
    reference_list: list,
    linear_interpolation: bool = False,
    upscale_function: str = "None",
    enable_bidirectional_filling: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Get the motion vectors for a given frame.

    THis function process the json file to retrieve the motion vectors and
    pre-process them.

    Args:
        frame_data (dict): Data from the JSON File.
        reference_list (list): List of reference frames.
        linear_interpolation (bool): Linear interpolation.
        upscale (str): Upscale to frame size.
        bidirectional_filling (bool): Bidirectional filling used to enhance motion vectors.

    Returns:
        tuple: Two numpy arrays containing the backward and forward motion vectors.
    """

    motion_vectors = np.array(frame_data["motionVectors"]) / 8
    motion_backward = motion_vectors[:, :, 0:2]
    motion_forward = motion_vectors[:, :, 2:4]

    if linear_interpolation:
        reference_frames = np.array(frame_data["referenceFrame"])
        reference_map_backward = reference_frames[:, :, 0]
        reference_map_forward = reference_frames[:, :, 1]

        def f(x):
            return frame_number - reference_list[x]

        distance_map_backward = np.vectorize(f)(reference_map_backward)
        distance_map_forward = np.vectorize(f)(reference_map_forward)

        motion_backward = motion_backward / distance_map_backward[:, :, np.newaxis]
        motion_forward = motion_forward / distance_map_forward[:, :, np.newaxis]

        if enable_bidirectional_filling:
            motion_backward, motion_forward = bidirectional_filling(
                motion_backward, motion_forward
            )

    if upscale_function != "None":
        motion_backward = upscale(upscale_function, motion_backward)
        motion_forward = upscale(upscale_function, motion_forward)

    return motion_backward, motion_forward


def initialize_unwrapping_dict() -> dict:
    """Initialize the unwrapping dictionary.

    AV1 order hints are cyclic, going from 0 to 127. For videos
    having more than 128 frames, the order hints will repeat.

    To retrieve the proper frame number based on the order hint,
    we use a dictionary to map the order hint to the frame number.

    This function initializes the dictionary with all the order hints
    set to -1.

    Returns:
        dict: Unwrapping dictionary.
    """
    unwrapping_dict: dict[int, int] = {}
    for i in range(128):
        unwrapping_dict[i] = -1
    return unwrapping_dict


def unwrap_order_hints(order_hints: list, unwrapping_dict: dict) -> list:
    """Unwrap order hints.

    AV1 order hints are cyclic, going from 0 to 127. For videos
    having more than 128 frames, the order hints will repeat.

    To retrieve the proper frame number based on the order hint,
    we use a dictionary to map the order hint to the frame number.

    Args:
        order_hints (list): List of order hints.
        unwrapping_dict (dict): Unwrapping dictionary.

    Returns:
        list: Unwrapped order hints.
    """

    unwrapped_order_hints = []

    for i in range(len(order_hints)):
        unwrapped_order_hints.append(
            order_hints[i] + 128 * unwrapping_dict[order_hints[i]]
        )

    return unwrapped_order_hints
