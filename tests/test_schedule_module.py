import collections

from schedule import Schedule2


def _make_schedule2():
    return Schedule2(
        version=1.0,
        Event="Scheduler",
        list=collections.deque(),
        state="stopped",
        is_stacking_paused=False,
        is_stacking=False,
        is_skip_requested=False,
        current_item_id="",
        item_number=0,
    )


def test_construct_schedule_item_does_not_reference_missing_ra_dec():
    # Regression: construct_schedule_item referenced self.ra / self.dec, which
    # Schedule2 (a pure schedule model) does not define, so a negative-RA float
    # mosaic raised AttributeError. It now rounds the supplied coordinates.
    sched = _make_schedule2()

    item = sched.construct_schedule_item(
        {
            "action": "start_mosaic",
            "params": {"ra": -1.23456, "dec": 2.34561, "is_j2000": True},
        }
    )

    assert item["params"]["ra"] == round(-1.23456, 4)
    assert item["params"]["dec"] == round(2.34561, 4)
    assert "schedule_item_id" in item
