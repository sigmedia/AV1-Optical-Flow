"""
 main.py

  Created by Julien Zouein on 18/03/2026.
  Copyright © 2026 Sigmedia.tv. All rights reserved.
  Copyright © 2026 Julien Zouein (zoueinj@tcd.ie)
----------------------------------------------------------------------------

Python file used to run the extraction pipeline.
"""

from pathlib import Path
import subprocess

import argparse
import cv2
import numpy as np
from tqdm import tqdm

from src.modules.dav1d_inspect import iter_frames
from src.modules.flow_io import flow_to_rgb
from src.modules.flow_io import writeFlowFile
from src.modules.json_processing import get_motion_vectors
from src.modules.json_processing import initialize_unwrapping_dict
from src.modules.json_processing import unwrap_order_hints
from src.modules.logger import start_logger
from src.modules.utils import check_ivf_file


def get_args_parser():
    """Function used to parse arguments from command line.

    Returns:
        argparse.Namespace: Namespace object containing the parsed arguments.
    """

    parser = argparse.ArgumentParser(
        "AV1-Optical-Flow: AV1 Motion Vectors extraction pipeline",
        description="Extract and pre-process AV1's motion vectors.",
        add_help=True,
    )

    parser.add_argument(
        "--input_file",
        type=str,
        required=False,
        help="Path to the input AV1 file.",
    )

    parser.add_argument(
        "--output_directory",
        type=str,
        required=False,
        help="Path to the output directory.",
    )

    parser.add_argument(
        "--bidirectional_filling",
        action="store_true",
        default=False,
        help="Enable bidirectional filling of the motion vectors.",
    )

    parser.add_argument(
        "--upscale_function",
        type=str,
        required=False,
        help="Function to use for upscaling the motion vectors.",
        choices=["bicubic", "nearest", "bilinear", "area", "lanczos"],
        default="None",
    )

    parser.add_argument(
        "--linear_interpolation",
        action="store_true",
        default=False,
        help="Enable linear interpolation of the motion vectors.",
    )

    parser.add_argument(
        "--display",
        required=False,
        default=False,
        action="store_true",
        help="Display the motion vectors as RGB images.",
    )

    parser.add_argument(
        "--threads",
        type=int,
        required=False,
        default=0,
        help="Number of dav1d decoder threads (0 = auto / all logical cores).",
    )

    parser.add_argument(
        "--logger_level",
        type=str,
        required=False,
        help="Level of the logger.",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
    )

    parser.add_argument(
        "--version",
        required=False,
        default=False,
        action="store_true",
        help="Display the version of the Software and main components used.",
    )

    return parser.parse_args()


def get_version():
    """Display the version of the Software and main components.


    Returns:
        str: Version of the Software and main components used.
    """

    version = "1.0.0"

    print(f"AV1-Optical-Flow: {version}")

    command_dav1d = "cd src/third_parties/dav1d && git describe --tags"
    result = subprocess.run(command_dav1d, shell=True, stdout=subprocess.PIPE)
    dav1d_version = result.stdout.decode("utf-8").strip()
    print(f"dav1d version: {dav1d_version}")


if __name__ == "__main__":
    args = get_args_parser()
    if args.version:
        get_version()
        exit(0)

    logger = start_logger(path="./", level=args.logger_level)

    if args.input_file is None:
        logger.error("Error: Input file is required.")
        exit(1)

    if args.output_directory is None:
        logger.error("Error: Output directory is required.")
        exit(1)

    if not check_ivf_file(args.input_file):
        logger.error("Error: Input file is not an IVF file.")
        exit(1)

    logger.info(f"Output directory: {args.output_directory}")
    Path(args.output_directory).mkdir(parents=True, exist_ok=True)

    logger.info("Decoding bitstream and extracting motion vectors with dav1d")

    unwrapping_dict = initialize_unwrapping_dict()
    logged_dimensions = False

    for frame in tqdm(
        iter_frames(args.input_file, n_threads=args.threads),
        desc="Processing frames",
    ):
        if not logged_dimensions:
            logger.info(f"   >>> Width: {frame['width']}")
            logger.info(f"   >>> Height: {frame['height']}")
            logged_dimensions = True

        # AV1 order hints are cyclic (0-127); unwrap to an absolute frame number.
        order_hint = frame["frame_offset"]
        unwrapping_dict[order_hint] += 1
        frame_number = order_hint + 128 * unwrapping_dict[order_hint]

        logger.debug(f"Processing frame {frame_number}")

        # Reference order hints [INTRA, LAST, LAST2, LAST3, GOLDEN, BWDREF,
        # ALTREF2, ALTREF], provided per-frame by dav1d (replaces av1_parser),
        # unwrapped to absolute frame numbers.
        frame_ref_index = [0] + list(frame["refpoc"])
        frame_ref_index = unwrap_order_hints(frame_ref_index, unwrapping_dict)

        # Adapt the in-memory arrays to get_motion_vectors' expected schema.
        frame_data = {
            "motionVectors": frame["motion_vectors"],
            "referenceFrame": frame["reference_map"],
        }

        motion_backward, motion_forward = get_motion_vectors(
            frame_data,
            frame_number,
            frame_ref_index,
            linear_interpolation=args.linear_interpolation,
            upscale_function=args.upscale_function,
            enable_bidirectional_filling=args.bidirectional_filling,
        )

        writeFlowFile(
            motion_backward,
            f"{args.output_directory}/motion_backward_{frame_number}.flo5",
        )
        writeFlowFile(
            motion_forward,
            f"{args.output_directory}/motion_forward_{frame_number}.flo5",
        )

        if args.display:
            display_backward = flow_to_rgb(motion_backward)
            display_backward = cv2.cvtColor(display_backward, cv2.COLOR_RGB2BGR)
            display_forward = flow_to_rgb(motion_forward)
            display_forward = cv2.cvtColor(display_forward, cv2.COLOR_RGB2BGR)

            # Concatenate the two images horizontally
            display = np.concatenate((display_backward, display_forward), axis=1)
            cv2.imshow("Motion Vectors", display)
            cv2.waitKey(1)

    logger.info("Done processing video file")
