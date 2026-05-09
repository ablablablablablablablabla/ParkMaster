# tests/test_find_nearby_parking_camera.py
"""
Tests for the camera-based filter in find_nearby_parking.

Conftest makes @tools.FunctionTool a no-op, so find_nearby_parking
is a plain callable after import.
"""
from unittest.mock import MagicMock, patch
import state


def _setup_spots():
    state.PARKING_SPOTS.clear()
    state.PARKING_SPOTS['spot_sajam_1'] = {
        'id': 'spot_sajam_1', 'title': 'Lot Sajam', 'city': 'Belgrade',
        'lat': 44.794, 'lng': 20.4302, 'status': 'active',
        'base_price_per_hour': 2.0, 'rules': 'No overnight parking.',
    }
    state.PARKING_SPOTS['spot_other_1'] = {
        'id': 'spot_other_1', 'title': 'Other Spot', 'city': 'Belgrade',
        'lat': 44.800, 'lng': 20.435, 'status': 'active',
        'base_price_per_hour': 2.5, 'rules': 'Standard rules.',
    }


def _mock_http_client(is_occupied: bool):
    """Return a context-manager mock for httpx.Client that returns given status."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'is_occupied': is_occupied, 'label': 'Occupated' if is_occupied else 'Empty', 'confidence': 0.9}

    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_ctx.get.return_value = mock_response

    mock_client_class = MagicMock(return_value=mock_ctx)
    return mock_client_class


def test_sajam_excluded_when_camera_occupied():
    import agents
    _setup_spots()
    with patch('agents.httpx.Client', _mock_http_client(is_occupied=True)):
        result = agents.find_nearby_parking(44.794, 20.430, 120)
    ids = [s['id'] for s in result]
    assert 'spot_sajam_1' not in ids
    assert 'spot_other_1' in ids


def test_sajam_included_when_camera_empty():
    import agents
    _setup_spots()
    with patch('agents.httpx.Client', _mock_http_client(is_occupied=False)):
        result = agents.find_nearby_parking(44.794, 20.430, 120)
    ids = [s['id'] for s in result]
    assert 'spot_sajam_1' in ids
    assert 'spot_other_1' in ids


def test_sajam_included_when_flask_unreachable():
    """Camera server down → safe fallback, spot appears normally."""
    import agents
    _setup_spots()
    mock_client_class = MagicMock(side_effect=Exception("connection refused"))
    with patch('agents.httpx.Client', mock_client_class):
        result = agents.find_nearby_parking(44.794, 20.430, 120)
    ids = [s['id'] for s in result]
    assert 'spot_sajam_1' in ids


def test_sajam_included_when_status_non_200():
    import agents
    _setup_spots()

    mock_response = MagicMock()
    mock_response.status_code = 503

    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_ctx.get.return_value = mock_response
    mock_client_class = MagicMock(return_value=mock_ctx)

    with patch('agents.httpx.Client', mock_client_class):
        result = agents.find_nearby_parking(44.794, 20.430, 120)
    ids = [s['id'] for s in result]
    assert 'spot_sajam_1' in ids


def test_other_spots_unaffected_by_camera():
    """Camera check must never drop spots other than spot_sajam_1."""
    import agents
    _setup_spots()
    with patch('agents.httpx.Client', _mock_http_client(is_occupied=True)):
        result = agents.find_nearby_parking(44.794, 20.430, 120)
    ids = [s['id'] for s in result]
    assert 'spot_other_1' in ids
