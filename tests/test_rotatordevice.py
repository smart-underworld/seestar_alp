from device.rotatordevice import RotatorDevice


class _Logger:
    def debug(self, *args, **kwargs):
        return None

    def info(self, *args, **kwargs):
        return None


def test_relative_move_does_not_subtract_sync_offset():
    # Regression: Move() (a RELATIVE move) computed
    #   _tgt_mech_pos = _mech_pos + delta - _pos_offset
    # wrongly subtracting the Sync offset. A relative delta in user coordinates
    # is the same delta in mechanical coordinates, so the offset must not apply.
    rot = RotatorDevice(_Logger())
    rot.start = lambda: None  # do not launch the mover timer thread
    rot._mech_pos = 100.0
    rot._pos_offset = 30.0  # as if Sync() had established an offset

    rot.Move(10.0)  # relative +10 degrees

    assert rot._tgt_mech_pos == 110.0  # mech + delta, offset NOT subtracted
