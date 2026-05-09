# tests/test_web_server_status.py
import sys
from unittest.mock import MagicMock, patch


def _import_web_server():
    """Import web_server with model loading neutralized."""
    # labels.txt exists on disk; keras load_model is already mocked via conftest
    with patch.dict('sys.modules', {'numpy': MagicMock()}):
        import web_server
    return web_server


def test_status_endpoint_returns_200_with_expected_keys():
    ws = _import_web_server()
    client = ws.app.test_client()
    response = client.get('/status')
    assert response.status_code == 200
    data = response.get_json()
    assert 'label' in data
    assert 'is_occupied' in data
    assert 'is_no_parking' in data
    assert 'confidence' in data


def test_status_returns_false_is_occupied_initially():
    ws = _import_web_server()
    ws.LAST_PREDICTION.update({'label': None, 'is_occupied': False, 'is_no_parking': False, 'confidence': 0.0})
    client = ws.app.test_client()
    data = client.get('/status').get_json()
    assert data['is_occupied'] is False
    assert data['label'] is None


def test_status_reflects_updated_prediction():
    ws = _import_web_server()
    ws.LAST_PREDICTION.update({
        'label': 'Occupated',
        'is_occupied': True,
        'is_no_parking': False,
        'confidence': 0.95,
    })
    client = ws.app.test_client()
    data = client.get('/status').get_json()
    assert data['is_occupied'] is True
    assert data['label'] == 'Occupated'
    assert data['confidence'] == 0.95
    ws.LAST_PREDICTION.update({'label': None, 'is_occupied': False, 'is_no_parking': False, 'confidence': 0.0})
