import enum

class NetworkMode(enum.Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    OFFLINE = "offline"
    PERSONAL_CLOUD = "personal_cloud"

class SecurityLevel(enum.Enum):
    STRONG = "strong"
    NORMAL = "normal"
    NORMAL_MINUS = "normal-minus"
    WEAK = "weak"

class DBMode(enum.Enum):
    LOCAL = "local"
    CACHE = "cache"
    REMOTE = "remote"