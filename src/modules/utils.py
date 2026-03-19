"""
 utils.py

  Created by Julien Zouein on 18/03/2026.
  Copyright © 2026 Sigmedia.tv. All rights reserved.
  Copyright © 2026 Julien Zouein (zoueinj@tcd.ie)
----------------------------------------------------------------------------

 Python file used to define all the utility functions.
"""

import re
import subprocess

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


def generate_inspect_json(input_file: str, output_folder: str) -> None:
    """Generate the JDON file using AOM inspect tool.

    To extract the metadata from an AV1 bitstream, we use inspect tool
    from AOM, that will generate a JSON file during the decoding process.

    Args:
        input_file (str): Path to the input AV1 file.
        output_folder (str): Path to the output folder.

    Returns:
        bool: True if the JSON file is generated, False otherwise.
    """

    command = f"./src/third_parties/aom_build/examples/inspect {input_file} "
    command += f"-mv -r > {output_folder}/inspect.json"
    subprocess.run(command, shell=True)


def get_frame_ref_index(input_file: str, output_folder: str) -> list:
    """This function is used to get the order hints out of AV1 bitstream.

    When processing the metadata, if we check from reference frame index, we have
    a number representing the type of frame (last, golden, etc). However, in our
    case we would rather have the frame number.
    The conversion array between frame type and frame number is the order hints.

    Args:
        temp_folder: Path to the temporary folder.

    Returns:
        A list of all the order hints (list of integers).
    """

    # Call av1parser tool to analyze the bitstrean and save this analysis in a txt file.
    command = f"cd src/third_parties/av1parser && cargo run {input_file} -vv"
    command += f" > {output_folder}/output_bitstream.txt && cd ../../.."

    subprocess.run(command, shell=True)

    pattern = re.compile("order_hints: \[(.*?)\]")
    with open(
        f"{output_folder}/output_bitstream.txt", mode="rt", encoding="utf-8"
    ) as docFile:
        doc = docFile.read()
        refs_frame_index = re.findall(pattern, doc)

    return refs_frame_index


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
