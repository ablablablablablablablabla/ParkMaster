# tests/conftest.py
import sys
from unittest.mock import MagicMock


def pytest_configure(config):
    # Make @tools.FunctionTool a no-op — agent functions stay directly callable
    mock_adk_tools = MagicMock()
    mock_adk_tools.FunctionTool = lambda f: f

    mock_adk = MagicMock()
    mock_adk.tools = mock_adk_tools

    sys.modules.update({
        'google': MagicMock(),
        'google.adk': mock_adk,
        'google.adk.tools': mock_adk_tools,
        'google.adk.agents': MagicMock(),
        'google.adk.runners': MagicMock(),
        'google.adk.models': MagicMock(),
        'google.adk.models.lite_llm': MagicMock(),
        'google.genai': MagicMock(),
        'google.genai.types': MagicMock(),
        # ML libs — load_model returns a MagicMock, no file I/O
        'tf_keras': MagicMock(),
        'tf_keras.models': MagicMock(),
        # Image processing
        'PIL': MagicMock(),
        'PIL.Image': MagicMock(),
        'PIL.ImageOps': MagicMock(),
        # Flask extension
        'flask_cors': MagicMock(),
        # Telegram
        'telegram': MagicMock(),
        'telegram.ext': MagicMock(),
        'telegram.constants': MagicMock(),
        # Solana / payments
        'solders': MagicMock(),
        'solders.keypair': MagicMock(),
        'solders.pubkey': MagicMock(),
        'solders.transaction': MagicMock(),
        'solders.signature': MagicMock(),
        'base58': MagicMock(),
        'dotenv': MagicMock(),
    })
