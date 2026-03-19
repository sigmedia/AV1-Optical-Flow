"""
 main.py

  Created by Julien Zouein on 18/03/2026.
  Copyright © 2026 Sigmedia.tv. All rights reserved.
  Copyright © 2026 Julien Zouein (zoueinj@tcd.ie)
----------------------------------------------------------------------------

Python file used to run the extraction pipeline.
"""

import subprocess

import argparse


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

    if args.input_file is None:
        print("Error: Input file is required.")
        exit(1)

    if args.output_directory is None:
        print("Error: Output directory is required.")
        exit(1)
