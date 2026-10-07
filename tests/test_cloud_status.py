from franklinwh_direct_connect_bridge import cloud_status as cs


def test_programme_label_variants():
    # The bug: a single DICT (VPP programme object) was iterated → its KEYS dumped.
    prog_dict = {"VPP mode": 1, "flag": 0, "programId": 7, "programName": "Amber Flex",
                 "partnerName": "Amber", "postcode": "2069"}
    assert cs._programme_label(prog_dict) == "Amber"          # partnerName wins, not the keys
    # list of dicts
    assert cs._programme_label([{"programName": "Peak Rewards"}]) == "Peak Rewards"
    # list of strings
    assert cs._programme_label(["Flex", "Flex"]) == "Flex"    # deduped
    # empty / none
    assert cs._programme_label(None) is None
    assert cs._programme_label({}) is None
