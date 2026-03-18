"""
 logger.py

  Created by Julien Zouein on 18/03/2026.
  Copyright © 2026 Sigmedia.tv. All rights reserved.
  Copyright © 2026 Julien Zouein (zoueinj@tcd.ie)
----------------------------------------------------------------------------

Python file used to initialize the logger.
"""

import datetime
import os
import sys

from loguru import logger


def start_logger(
    file_name: str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
    path: str = "",
    level: str = "INFO",
):
    """Function used to initialize the logger.

    Args:
        file_name (str): Name of the file to log to.
        path (str): Path to the directory to log to.
        level (str): Level of the logger.

    Returns:
        logger: Logger object.
    """

    logger.remove()

    logs_format = (
        "<fg 255,215,0>{time:YYYY-MM-DD HH:mm:ss}</fg 255,215,0> "
        "| <fg 49,140,231>{message}</fg 49,140,231>"
    )

    if path and file_name != "pytest" and file_name != "pytest_logger":
        logger.add(
            sys.stderr,
            level=level,
            colorize=True,
            format=logs_format,
        )

        sink_name = os.path.join(path, "logs", f"{file_name}.txt")
        logger.add(
            sink=sink_name,
            level=level,
        )

    if file_name == "pytest_logger":
        logs_format = "PYTEST | {message}"
        logger.add(
            sys.stderr,
            level=level,
            colorize=True,
            format=logs_format,
        )

        sink_name = f"{path}/logs/pytest_logger.txt"
        logger.add(sink=sink_name, level=level)

    return logger
