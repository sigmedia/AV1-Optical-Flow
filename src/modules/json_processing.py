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
