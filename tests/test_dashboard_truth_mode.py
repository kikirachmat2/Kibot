from Core.Intelligence.kibot_dashboard import _build_control_plane_payload


def test_dashboard_control_plane_has_web3_truth_blocks():
    payload = _build_control_plane_payload()
    assert "venues" in payload
    assert "web3" in payload
    assert "web3_exit" in payload
    assert "allow_new_live_orders" in payload["mode"]
    assert "reason" in payload["venues"]["indodax_real"]
    assert "phantom" not in payload["venues"]
