import os

from mcp_can.dbc import decode_frame, load_dbc, signal_int


def _db():
    db_path = os.path.join(os.path.dirname(__file__), "..", "vehicle.dbc")
    return load_dbc(os.path.abspath(db_path))


def test_dbc_loads_and_has_messages():
    db = _db()
    assert db is not None
    names = {m.name for m in db.messages}
    assert {"ENGINE_STATUS", "ABS_STATUS", "AIRBAG_STATUS", "BODY_STATUS"}.issubset(names)


def test_signal_int_handles_plain_numbers():
    assert signal_int(5) == 5
    assert signal_int(5.0) == 5


def test_signal_int_unwraps_named_signal_value():
    # DIAGNOSTIC_REQUEST's SERVICE_ID has a VAL_ choice table (e.g. 0x22 ->
    # "READ_DATA_BY_ID"), so decode() returns a NamedSignalValue for known
    # values -- int() on that raises TypeError unless unwrapped via signal_int.
    db = _db()
    msg = db.get_message_by_name("DIAGNOSTIC_REQUEST")
    data = msg.encode({"SERVICE_ID": 0x22, "PARAMETER_ID": 5, "DATA_FIELD": 0})
    decoded = decode_frame(db, msg.frame_id, data)
    assert str(decoded["SERVICE_ID"]) == "READ_DATA_BY_ID"
    assert signal_int(decoded["SERVICE_ID"]) == 0x22
