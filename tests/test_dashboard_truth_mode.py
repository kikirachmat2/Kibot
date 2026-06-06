from Core.Intelligence.kibot_dashboard import _build_control_plane_payload


def test_dashboard_control_plane_has_indodax_truth_blocks():
    payload = _build_control_plane_payload()
    assert "venues" in payload
    assert ("we" + "b3") not in payload
    assert ("we" + "b3_exit") not in payload
    assert "allow_new_live_orders" in payload["mode"]
    assert "reason" in payload["venues"]["indodax_real"]
    assert ("ph" + "antom") not in payload["venues"]
