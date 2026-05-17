from unittest.mock import MagicMock, patch


def test_main_loads_settings_constructs_server_and_runs():
    config = object()
    server = MagicMock()

    with patch("dhara.mcp.__main__.DharaSettings.load", return_value=config) as mock_load:
        with patch("dhara.mcp.__main__.DharaMCPServer", return_value=server) as mock_server:
            from dhara.mcp.__main__ import main

            main()

    mock_load.assert_called_once_with()
    mock_server.assert_called_once_with(config)
    server.run.assert_called_once_with()
