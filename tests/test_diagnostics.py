from mcp_can.diagnostics import (
    SERVICE_IDS,
    ecu_name_from_response_message,
    handle_service,
    response_code_name,
)


def test_start_session_and_reset_are_acknowledged_ok():
    for service in (SERVICE_IDS["START_DIAGNOSTIC_SESSION"], SERVICE_IDS["RESET_ECU"]):
        code, data = handle_service(service, parameter_id=0, data_field=0)
        assert response_code_name(code) == "OK"
        assert data == 0


def test_read_data_by_id_returns_deterministic_value():
    code, data = handle_service(SERVICE_IDS["READ_DATA_BY_ID"], parameter_id=5, data_field=0)
    assert response_code_name(code) == "OK"
    assert data == (5 * 37) % 0xFFFFFFFFFF


def test_unsupported_service_is_rejected():
    code, data = handle_service(SERVICE_IDS["WRITE_MEMORY"], parameter_id=0, data_field=0)
    assert response_code_name(code) == "SERVICE_NOT_SUPPORTED"
    assert data == 0


def test_unknown_response_code_is_labeled():
    assert response_code_name(255) == "UNKNOWN(0xff)"


def test_ecu_name_from_response_message():
    assert ecu_name_from_response_message("DIAGNOSTIC_RESPONSE_ENGINE") == "ENGINE"
