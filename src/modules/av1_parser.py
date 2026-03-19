"""
 av1_parser.py

  Created by Julien Zouein on 18/03/2026.
  Copyright © 2026 Sigmedia.tv. All rights reserved.
  Copyright © 2026 Julien Zouein (zoueinj@tcd.ie)
----------------------------------------------------------------------------

Minimal AV1 bitstream parser for extracting reference frame order hints
from IVF-wrapped AV1 streams. Replaces the external av1parser Rust tool.

Only the subset of the AV1 spec (AOM av1-isobmff / Section 5+6+7) needed
to reach ref_frame_idx in each frame header is implemented.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

NUM_REF_FRAMES = 8
REFS_PER_FRAME = 7

KEY_FRAME = 0
INTER_FRAME = 1
INTRA_ONLY_FRAME = 2
SWITCH_FRAME = 3

_SELECT_SCREEN_CONTENT_TOOLS = 2
_SELECT_INTEGER_MV = 2

_OBU_SEQUENCE_HEADER = 1
_OBU_FRAME_HEADER = 3
_OBU_FRAME = 6


# ---------------------------------------------------------------------------
# Bit-level reader
# ---------------------------------------------------------------------------


class _BitReader:
    __slots__ = ("_data", "_pos")

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def read(self, n: int) -> int:
        """Read *n* bits as an unsigned integer (MSB first)."""
        if n == 0:
            return 0
        val = 0
        for _ in range(n):
            byte_idx = self._pos >> 3
            bit_idx = 7 - (self._pos & 7)
            val = (val << 1) | ((self._data[byte_idx] >> bit_idx) & 1)
            self._pos += 1
        return val

    def read_uvlc(self) -> int:
        """Read an unsigned variable-length coded integer (AV1 spec 4.10.3)."""
        leading_zeros = 0
        while self.read(1) == 0:
            leading_zeros += 1
            if leading_zeros >= 32:
                return (1 << 32) - 1
        return self.read(leading_zeros) + (1 << leading_zeros) - 1


# ---------------------------------------------------------------------------
# LEB128 helper (used for OBU size fields)
# ---------------------------------------------------------------------------


def _read_leb128(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for i in range(8):
        b = data[offset + i]
        value |= (b & 0x7F) << (i * 7)
        if not (b & 0x80):
            return value, i + 1
    return value, 8


# ---------------------------------------------------------------------------
# Sequence header parameters (only those needed for frame-header parsing)
# ---------------------------------------------------------------------------


@dataclass
class _SeqParams:
    reduced_still_picture_header: bool = False
    decoder_model_info_present: bool = False
    equal_picture_interval: bool = False
    frame_presentation_time_length: int = 0
    operating_points_cnt: int = 1
    operating_point_idc: list[int] = field(default_factory=list)
    decoder_model_present_for_op: list[bool] = field(default_factory=list)
    buffer_delay_length: int = 0
    buffer_removal_time_length: int = 0
    frame_id_numbers_present: bool = False
    id_len: int = 0
    delta_frame_id_length: int = 0
    enable_order_hint: bool = False
    order_hint_bits: int = 0
    seq_force_screen_content_tools: int = _SELECT_SCREEN_CONTENT_TOOLS
    seq_force_integer_mv: int = _SELECT_INTEGER_MV


def _parse_seq_header(payload: bytes) -> _SeqParams:
    r = _BitReader(payload)
    sp = _SeqParams()

    _ = r.read(3)
    r.read(1)  # still_picture
    sp.reduced_still_picture_header = bool(r.read(1))

    if sp.reduced_still_picture_header:
        sp.operating_points_cnt = 1
        sp.operating_point_idc = [0]
        r.read(5)  # seq_level_idx[0]
        sp.decoder_model_present_for_op = [False]
    else:
        timing_info_present = bool(r.read(1))
        if timing_info_present:
            r.read(32)  # num_units_in_display_tick
            r.read(32)  # time_scale
            sp.equal_picture_interval = bool(r.read(1))
            if sp.equal_picture_interval:
                r.read_uvlc()  # num_ticks_per_picture_minus_1
            sp.decoder_model_info_present = bool(r.read(1))
            if sp.decoder_model_info_present:
                sp.buffer_delay_length = r.read(5) + 1
                r.read(32)  # num_units_in_decoding_tick
                sp.buffer_removal_time_length = r.read(5) + 1
                sp.frame_presentation_time_length = r.read(5) + 1

        initial_display_delay_present = bool(r.read(1))
        sp.operating_points_cnt = r.read(5) + 1
        sp.operating_point_idc = []
        sp.decoder_model_present_for_op = []
        for _ in range(sp.operating_points_cnt):
            sp.operating_point_idc.append(r.read(12))
            lvl = r.read(5)
            if lvl > 7:
                r.read(1)  # seq_tier
            if sp.decoder_model_info_present:
                present = bool(r.read(1))
                sp.decoder_model_present_for_op.append(present)
                if present:
                    r.read(sp.buffer_delay_length)  # decoder_buffer_delay
                    r.read(sp.buffer_delay_length)  # encoder_buffer_delay
                    r.read(1)  # low_delay_mode_flag
            else:
                sp.decoder_model_present_for_op.append(False)
            if initial_display_delay_present:
                if r.read(1):  # display_delay_present_for_this_op
                    r.read(4)  # initial_display_delay_minus_1

    fw_bits = r.read(4) + 1
    fh_bits = r.read(4) + 1
    r.read(fw_bits)  # max_frame_width_minus_1
    r.read(fh_bits)  # max_frame_height_minus_1

    if not sp.reduced_still_picture_header:
        sp.frame_id_numbers_present = bool(r.read(1))

    if sp.frame_id_numbers_present:
        dfid_m2 = r.read(4)
        afid_m1 = r.read(3)
        sp.delta_frame_id_length = dfid_m2 + 2
        sp.id_len = afid_m1 + dfid_m2 + 3

    r.read(1)  # use_128x128_superblock
    r.read(1)  # enable_filter_intra
    r.read(1)  # enable_intra_edge_filter

    if not sp.reduced_still_picture_header:
        r.read(1)  # enable_interintra_compound
        r.read(1)  # enable_masked_compound
        r.read(1)  # enable_warped_motion
        r.read(1)  # enable_dual_filter
        sp.enable_order_hint = bool(r.read(1))
        if sp.enable_order_hint:
            r.read(1)  # enable_jnt_comp
            r.read(1)  # enable_ref_frame_mvs

        if r.read(1):  # seq_choose_screen_content_tools
            sp.seq_force_screen_content_tools = _SELECT_SCREEN_CONTENT_TOOLS
        else:
            sp.seq_force_screen_content_tools = r.read(1)

        if sp.seq_force_screen_content_tools > 0:
            if r.read(1):  # seq_choose_integer_mv
                sp.seq_force_integer_mv = _SELECT_INTEGER_MV
            else:
                sp.seq_force_integer_mv = r.read(1)
        else:
            sp.seq_force_integer_mv = _SELECT_INTEGER_MV

        if sp.enable_order_hint:
            sp.order_hint_bits = r.read(3) + 1

    return sp


# ---------------------------------------------------------------------------
# Frame header helpers
# ---------------------------------------------------------------------------


def _get_relative_dist(a: int, b: int, bits: int) -> int:
    """Signed distance between order hints *a* and *b* (AV1 spec 5.9.26)."""
    diff = a - b
    m = 1 << (bits - 1)
    return (diff & (m - 1)) - (diff & m)


def _set_frame_refs(
    last_idx: int,
    gold_idx: int,
    ref_order_hint: list[int],
    order_hint: int,
    bits: int,
) -> list[int]:
    """Derive all ref_frame_idx from LAST and GOLDEN (AV1 spec 7.8)."""
    idx = [-1] * REFS_PER_FRAME
    idx[0] = last_idx  # LAST
    idx[3] = gold_idx  # GOLDEN

    used = [False] * NUM_REF_FRAMES
    used[last_idx] = True
    used[gold_idx] = True

    cur = 1 << (bits - 1)
    shifted = [
        cur + _get_relative_dist(ref_order_hint[i], order_hint, bits)
        for i in range(NUM_REF_FRAMES)
    ]

    def _best(cond, prefer_larger: bool, *, any_slot: bool = False) -> int:
        best = -1
        best_h = 0
        for i in range(NUM_REF_FRAMES):
            if not any_slot and used[i]:
                continue
            h = shifted[i]
            if not cond(h):
                continue
            if (
                best < 0
                or (prefer_larger and h >= best_h)
                or (not prefer_larger and h < best_h)
            ):
                best, best_h = i, h
        return best

    # ALTREF (idx 6): largest forward hint
    ref = _best(lambda h: h >= cur, prefer_larger=True)
    if ref >= 0:
        idx[6] = ref
        used[ref] = True

    # BWDREF (idx 4): smallest forward hint
    ref = _best(lambda h: h >= cur, prefer_larger=False)
    if ref >= 0:
        idx[4] = ref
        used[ref] = True

    # ALTREF2 (idx 5): next smallest forward hint
    ref = _best(lambda h: h >= cur, prefer_larger=False)
    if ref >= 0:
        idx[5] = ref
        used[ref] = True

    # Remaining backward slots: largest backward hint
    for slot in (1, 2, 4, 5, 6):  # LAST2, LAST3, BWDREF, ALTREF2, ALTREF
        if idx[slot] >= 0:
            continue
        ref = _best(lambda h: h < cur, prefer_larger=True)
        if ref >= 0:
            idx[slot] = ref
            used[ref] = True

    # Fallback: overall smallest shifted hint (including used slots)
    fallback = _best(lambda _: True, prefer_larger=False, any_slot=True)
    for i in range(REFS_PER_FRAME):
        if idx[i] < 0:
            idx[i] = fallback

    return idx


# ---------------------------------------------------------------------------
# Uncompressed frame header parser
# ---------------------------------------------------------------------------


def _parse_frame_header(
    payload: bytes,
    sp: _SeqParams,
    ref_oh: list[int],
    ref_ft: list[int],
    temporal_id: int,
    spatial_id: int,
) -> list[int] | None:
    """Parse the uncompressed header up to ref_frame_idx.

    *ref_oh* (RefOrderHint) and *ref_ft* (RefFrameType) are updated in-place.
    Returns 7 reference order hints, or ``None`` for show_existing_frame.
    """
    r = _BitReader(payload)
    ALL_FRAMES = (1 << NUM_REF_FRAMES) - 1

    # -- show_existing_frame / frame_type / show_frame / error_resilient ----
    if sp.reduced_still_picture_header:
        frame_type = KEY_FRAME
        show_frame = True
        error_resilient_mode = True
    else:
        if r.read(1):  # show_existing_frame
            slot = r.read(3)
            if sp.decoder_model_info_present and not sp.equal_picture_interval:
                r.read(sp.frame_presentation_time_length)
            if sp.frame_id_numbers_present:
                r.read(sp.id_len)
            if ref_ft[slot] == KEY_FRAME:
                oh = ref_oh[slot]
                for i in range(NUM_REF_FRAMES):
                    ref_oh[i] = oh
                    ref_ft[i] = KEY_FRAME
            return None

        frame_type = r.read(2)
        show_frame = bool(r.read(1))

        if (
            show_frame
            and sp.decoder_model_info_present
            and not sp.equal_picture_interval
        ):
            r.read(sp.frame_presentation_time_length)

        if not show_frame:
            r.read(1)  # showable_frame

        if frame_type == SWITCH_FRAME or (frame_type == KEY_FRAME and show_frame):
            error_resilient_mode = True
        else:
            error_resilient_mode = bool(r.read(1))

    frame_is_intra = frame_type in (KEY_FRAME, INTRA_ONLY_FRAME)

    # -- disable_cdf_update -------------------------------------------------
    r.read(1)

    # -- allow_screen_content_tools / force_integer_mv ----------------------
    if sp.seq_force_screen_content_tools == _SELECT_SCREEN_CONTENT_TOOLS:
        allow_scc = bool(r.read(1))
    else:
        allow_scc = sp.seq_force_screen_content_tools > 0

    if allow_scc and sp.seq_force_integer_mv == _SELECT_INTEGER_MV:
        r.read(1)  # force_integer_mv

    # -- current_frame_id ---------------------------------------------------
    if sp.frame_id_numbers_present:
        r.read(sp.id_len)

    # -- frame_size_override_flag -------------------------------------------
    if frame_type != SWITCH_FRAME and not sp.reduced_still_picture_header:
        r.read(1)

    # -- order_hint ---------------------------------------------------------
    order_hint = r.read(sp.order_hint_bits)

    # -- primary_ref_frame --------------------------------------------------
    if not (frame_is_intra or error_resilient_mode):
        r.read(3)

    # -- decoder model buffer_removal_time ----------------------------------
    if sp.decoder_model_info_present:
        if r.read(1):  # buffer_removal_time_present
            for op in range(sp.operating_points_cnt):
                if sp.decoder_model_present_for_op[op]:
                    idc = sp.operating_point_idc[op]
                    in_t = (idc >> temporal_id) & 1
                    in_s = (idc >> (spatial_id + 8)) & 1
                    if idc == 0 or (in_t and in_s):
                        r.read(sp.buffer_removal_time_length)

    # -- refresh_frame_flags ------------------------------------------------
    if frame_type == SWITCH_FRAME or (frame_type == KEY_FRAME and show_frame):
        refresh = ALL_FRAMES
    else:
        refresh = r.read(8)

    if frame_type == KEY_FRAME and show_frame:
        for i in range(NUM_REF_FRAMES):
            ref_oh[i] = 0
            ref_ft[i] = KEY_FRAME

    # -- ref_frame_idx (inter frames only) ----------------------------------
    result = [0] * REFS_PER_FRAME

    if not frame_is_intra:
        frame_refs_short = False
        ref_frame_idx: list[int] = []

        if sp.enable_order_hint:
            frame_refs_short = bool(r.read(1))
            if frame_refs_short:
                last_idx = r.read(3)
                gold_idx = r.read(3)
                ref_frame_idx = _set_frame_refs(
                    last_idx,
                    gold_idx,
                    ref_oh,
                    order_hint,
                    sp.order_hint_bits,
                )

        for i in range(REFS_PER_FRAME):
            if not frame_refs_short:
                ref_frame_idx.append(r.read(3))
            if sp.frame_id_numbers_present:
                r.read(sp.delta_frame_id_length)

        result = [ref_oh[idx] for idx in ref_frame_idx]

    # -- update reference buffer --------------------------------------------
    for i in range(NUM_REF_FRAMES):
        if refresh & (1 << i):
            ref_oh[i] = order_hint
            ref_ft[i] = frame_type

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_frame_ref_order_hints(filepath: str) -> list[list[int]]:
    """Parse an IVF-wrapped AV1 bitstream and return per-frame reference order hints.

    Each entry is a list of 7 order hints corresponding to
    ``[LAST, LAST2, LAST3, GOLDEN, BWDREF, ALTREF2, ALTREF]``.
    Intra/key frames produce ``[0, 0, 0, 0, 0, 0, 0]``.
    ``show_existing_frame`` OBUs are skipped (no entry produced).

    Args:
        filepath: Path to an IVF file containing an AV1 bitstream.

    Returns:
        A list of order-hint lists, one per decoded frame in decode order.
    """
    result: list[list[int]] = []
    sp: _SeqParams | None = None
    ref_oh = [0] * NUM_REF_FRAMES
    ref_ft = [KEY_FRAME] * NUM_REF_FRAMES

    with open(filepath, "rb") as f:
        header = f.read(32)
        if len(header) < 32 or header[:4] != b"DKIF":
            raise ValueError(f"Not a valid IVF file: {filepath}")

        while True:
            pkt_hdr = f.read(12)
            if len(pkt_hdr) < 12:
                break
            pkt_size = struct.unpack("<I", pkt_hdr[:4])[0]
            if pkt_size == 0:
                break
            pkt_data = f.read(pkt_size)
            if len(pkt_data) < pkt_size:
                break

            seen_frame_header = False
            pos = 0
            while pos < len(pkt_data):
                hdr_byte = pkt_data[pos]
                pos += 1
                obu_type = (hdr_byte >> 3) & 0xF
                ext_flag = (hdr_byte >> 2) & 1
                has_size = (hdr_byte >> 1) & 1

                t_id = s_id = 0
                if ext_flag:
                    ext_byte = pkt_data[pos]
                    pos += 1
                    t_id = (ext_byte >> 5) & 7
                    s_id = (ext_byte >> 3) & 3

                if has_size:
                    obu_size, consumed = _read_leb128(pkt_data, pos)
                    pos += consumed
                else:
                    obu_size = len(pkt_data) - pos

                obu_payload = pkt_data[pos : pos + obu_size]
                pos += obu_size

                if obu_type == _OBU_SEQUENCE_HEADER:
                    sp = _parse_seq_header(obu_payload)

                elif (
                    obu_type in (_OBU_FRAME_HEADER, _OBU_FRAME)
                    and not seen_frame_header
                ):
                    seen_frame_header = True
                    if sp is None:
                        raise ValueError("Frame header found before sequence header")
                    hints = _parse_frame_header(
                        obu_payload,
                        sp,
                        ref_oh,
                        ref_ft,
                        t_id,
                        s_id,
                    )
                    if hints is not None:
                        result.append(hints)

    return result
