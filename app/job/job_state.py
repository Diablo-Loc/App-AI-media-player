from enum import Enum

class JobState(str, Enum):
    IDLE = "idle"
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"