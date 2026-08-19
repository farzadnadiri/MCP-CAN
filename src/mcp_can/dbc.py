from functools import lru_cache
from typing import Any, Dict, Union, cast

import cantools


@lru_cache(maxsize=4)
def load_dbc(path: str) -> cantools.database.Database:
    # load_file() also supports diagnostics (.cdd) databases; this project only
    # ever loads CAN (.dbc) files, so the result is always a CAN Database.
    db = cantools.database.load_file(path)
    return cast(cantools.database.Database, db)


def decode_frame(
    db: cantools.database.Database,
    arbitration_id: int,
    data: Union[bytes, bytearray],
) -> Dict[str, Any]:
    message = db.get_message_by_frame_id(arbitration_id)
    decoded = message.decode(bytes(data))
    return cast(Dict[str, Any], decoded)


def signal_int(value: Any) -> int:
    """Coerce a decoded signal value to a plain int.

    A signal with a VAL_ choice table (e.g. an enum-like SERVICE_ID or
    RESPONSE_CODE) decodes to a `cantools.database.NamedSignalValue` rather
    than a raw int, and `int(NamedSignalValue)` raises TypeError — this
    unwraps it via its `.value` attribute, falling through unchanged for
    signals that decode to a plain number already.
    """
    return int(getattr(value, "value", value))

