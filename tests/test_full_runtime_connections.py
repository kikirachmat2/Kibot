from Core.Intelligence.kibot_dashboard import _build_control_plane_payload


def test_control_plane_exposes_autonomous_sizing_and_indodax_only():
    payload = _build_control_plane_payload()
    assert "autonomous_sizing" in payload
    assert ("we" + "b3") not in payload
    assert "meme_hunter" not in payload
    assert "route_live_ready" in payload
    assert "current_entry_approved" in payload
