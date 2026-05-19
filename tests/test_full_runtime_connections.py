from Core.Intelligence.kibot_dashboard import _build_control_plane_payload


def test_control_plane_exposes_autonomous_sizing_and_web3():
    payload = _build_control_plane_payload()
    assert "autonomous_sizing" in payload
    assert "web3" in payload
    assert "meme_hunter" in payload["web3"]
    assert "route_live_ready" in payload
    assert "current_entry_approved" in payload

