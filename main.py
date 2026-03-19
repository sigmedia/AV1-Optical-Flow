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
import tempfile

import argparse
import cv2
import ijson
from tqdm import tqdm

from src.modules.flow_io import writeFlowFile
from src.modules.json_processing import get_motion_vectors
from src.modules.json_processing import initialize_unwrapping_dict
from src.modules.json_processing import unwrap_order_hints
from src.modules.logger import start_logger
from src.modules.utils import check_ivf_file
from src.modules.utils import generate_inspect_json
from src.modules.utils import get_frame_ref_index


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
        help="Enable linear interpolation of the motion vectors.",
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

    command_aom = "cd src/third_parties/aom && git describe --tags"
    result = subprocess.run(command_aom, shell=True, stdout=subprocess.PIPE)
    aom_version = result.stdout.decode("utf-8").strip()
    print(f"AOM version: {aom_version}")


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

    with tempfile.TemporaryDirectory(delete=True) as tmp_dir:
        logger.debug(f"Temporary directory: {tmp_dir}")

        logger.info("Generating Inspect Json file")

        generate_inspect_json(args.input_file, tmp_dir)

        logger.info("Reading video file to get video information")
        cap = cv2.VideoCapture(args.input_file)

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        logger.info(f"   >>> Total frames: {total_frames}")
        logger.info(f"   >>> Width: {width}")
        logger.info(f"   >>> Height: {height}")

        cap.release()

        logger.info("Getting frame reference index")
        frames_ref_index = get_frame_ref_index(args.input_file, tmp_dir)

        frame_number = 0
        cursor = 0

        unwrapping_dict = initialize_unwrapping_dict()

        with open(f"{tmp_dir}/inspect.json", "rb") as json_file:
            for frame_data in tqdm(
                ijson.items(json_file, "item"),
                total=total_frames,
                desc="Processing frames",
            ):
                if frame_number == total_frames - 1:
                    break

                frame_number = frame_data["frame"]
                unwrapping_dict[frame_number] += 1
                frame_number = frame_number + 128 * unwrapping_dict[frame_number]

                logger.debug(f"Processing frame {frame_number}")

                frame_ref_index = eval(frames_ref_index[frame_number])
                frame_ref_index = unwrap_order_hints(frame_ref_index, unwrapping_dict)

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

    logger.info("Done processing video file")
