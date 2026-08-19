from dataclasses import dataclass


@dataclass
class Frame:
    timestamp: float
    arbitration_id: int
    data: bytes

