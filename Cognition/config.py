"""Vision PAL Cognition Engine - Configuration"""

# MQTT
MQTT_BROKER = "192.168.3.5"
MQTT_PORT = 1883

# MQTT Topics
TOPIC_PERCEPTION = "vision_pal/perception/objects"
TOPIC_COLLISION = "vision_pal/perception/collision"
TOPIC_AFFECT = "vision_pal/affect/state"
TOPIC_MEMORY = "vision_pal/memory/recall"
TOPIC_PROMPT = "vision_pal/prompt/current"
TOPIC_SCENE = "vision_pal/perception/scene"
TOPIC_UMWELT = "vision_pal/umwelt/state"
TOPIC_EFFECT = "vision_pal/effect"
TOPIC_MOVE = "vision_pal/move"
TOPIC_STATUS = "vision_pal/status"

# Body / Survival topics
TOPIC_BODY = "vision_pal/body/state"           # JetBot → body sensor data
TOPIC_SURVIVAL = "vision_pal/survival/state"   # survival engine → needs/drives
TOPIC_SURVIVAL_ACTION = "vision_pal/survival/action"  # survival engine → autonomous actions

# AsyncVLA topics
TOPIC_EDGE = "vision_pal/edge/state"           # Edge層 → CNN予測状態
TOPIC_VLA = "vision_pal/vla/state"             # VLAオーケストレータ → 統合状態

# JetBot Camera
MJPEG_URL = "http://192.168.3.8:8554/stream"
SNAPSHOT_URL = "http://192.168.3.8:8554/snapshot"

# Cognition cycle
CYCLE_INTERVAL = 2.0  # seconds

# Perception - DNN model paths (Jetson host)
DNN_PROTOTXT = "/home/haltyt/models/deploy.prototxt"
DNN_MODEL = "/home/haltyt/models/res10_300x300_ssd_iter_140000.caffemodel"
DNN_CONFIDENCE = 0.2

# Affect - emotion mapping
EMOTIONS = {
    "curious": {"valence": 0.7, "arousal": 0.5, "color": "#FFD700"},
    "excited": {"valence": 0.9, "arousal": 0.8, "color": "#FF6B35"},
    "calm": {"valence": 0.5, "arousal": 0.2, "color": "#87CEEB"},
    "anxious": {"valence": 0.3, "arousal": 0.7, "color": "#8B5CF6"},
    "happy": {"valence": 0.9, "arousal": 0.6, "color": "#F59E0B"},
    "lonely": {"valence": 0.2, "arousal": 0.2, "color": "#6366F1"},
    "startled": {"valence": 0.3, "arousal": 0.9, "color": "#EF4444"},
    "bored": {"valence": 0.4, "arousal": 0.1, "color": "#9CA3AF"},
}

# Prompt building
PROMPT_STYLE_PREFIX = "digital art, ethereal, dreamlike, soft particles"
PROMPT_NEGATIVE = "text, watermark, ugly, blurry"
SD_STRENGTH = 0.6  # img2img strength (0=original, 1=full generation)
