import cantools

from mcp_can.config import DEFAULT_DBC_PATH
from mcp_can.dbc import decode_frame


def test_encode_decode_roundtrip_engine_status():
    db = cantools.database.load_file(DEFAULT_DBC_PATH)
    msg = db.get_message_by_name("ENGINE_STATUS")
    signals = {
        "ENGINE_SPEED": 1500,
        "ENGINE_TEMP": 80,
        "THROTTLE_POSITION": 20,
        "ENGINE_LOAD": 30,
        "FUEL_LEVEL": 50,
    }
    data = msg.encode(signals)
    decoded = decode_frame(db, msg.frame_id, data)
    for key, value in signals.items():
        assert key in decoded
        # Allow small floating rounding differences
        assert abs(decoded[key] - value) < 1.0


