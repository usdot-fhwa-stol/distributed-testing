"""SAE J2735 (2016 and later) constants used by the BSM model.

Value ranges, LSB scales and "unavailable" sentinels follow the J2735 data
dictionary. Enumerated names are spelled exactly as in the standard (including
the standard's own spelling of ``schooldBusLights``) because asn1tools uses the
identifier text as the Python value.

This file contains no ASN.1 from the standard. The ASN.1 itself is licensed by
SAE and is loaded at runtime from ``asn1/`` (see asn1/README.md).
"""

# --- DSRCmsgID (MessageFrame.messageId) -------------------------------------
MSG_ID_MAP = 18
MSG_ID_SPAT = 19
MSG_ID_BSM = 20
MSG_ID_EVA = 22  # EmergencyVehicleAlert
MSG_ID_RSA = 27
MSG_ID_SRM = 29
MSG_ID_SSM = 30
MSG_ID_TIM = 31
MSG_ID_PSM = 32

# --- PartII-Id ---------------------------------------------------------------
PARTII_VEHICLE_SAFETY = 0      # VehicleSafetyExtensions
PARTII_SPECIAL_VEHICLE = 1     # SpecialVehicleExtensions
PARTII_SUPPLEMENTAL = 2        # SupplementalVehicleExtensions

PARTII_TYPE_NAMES = {
    PARTII_VEHICLE_SAFETY: "VehicleSafetyExtensions",
    PARTII_SPECIAL_VEHICLE: "SpecialVehicleExtensions",
    PARTII_SUPPLEMENTAL: "SupplementalVehicleExtensions",
}

# --- BSMcoreData scales and sentinels --------------------------------------
LATLON_LSB_DEG = 1e-7
LAT_UNAVAILABLE = 900000001
LON_UNAVAILABLE = 1800000001
LAT_MIN, LAT_MAX = -900000000, 900000000
LON_MIN, LON_MAX = -1799999999, 1800000000

ELEV_LSB_M = 0.1
ELEV_UNAVAILABLE = -4096
ELEV_MIN, ELEV_MAX = -4095, 61439

SEMI_AXIS_LSB_M = 0.05
SEMI_AXIS_UNAVAILABLE = 255
SEMI_AXIS_MAX = 254
ORIENTATION_LSB_DEG = 360.0 / 65535.0
ORIENTATION_UNAVAILABLE = 65535

SPEED_LSB_MPS = 0.02
SPEED_UNAVAILABLE = 8191
SPEED_MAX = 8190  # 8190 means >= 163.8 m/s

HEADING_LSB_DEG = 0.0125
HEADING_UNAVAILABLE = 28800
HEADING_MAX = 28799

STEER_WHEEL_LSB_DEG = 1.5
STEER_WHEEL_UNAVAILABLE = 127
STEER_WHEEL_MIN, STEER_WHEEL_MAX = -126, 126

ACCEL_LSB_MPS2 = 0.01
ACCEL_UNAVAILABLE = 2001
ACCEL_MIN, ACCEL_MAX = -2000, 2000

VERT_ACCEL_LSB_G = 0.02
VERT_ACCEL_UNAVAILABLE = -127
VERT_ACCEL_MIN, VERT_ACCEL_MAX = -126, 127

YAW_RATE_LSB_DPS = 0.01
YAW_RATE_MIN, YAW_RATE_MAX = -32767, 32767

VEHICLE_WIDTH_MAX_CM = 1023
VEHICLE_LENGTH_MAX_CM = 4095

SEC_MARK_UNAVAILABLE = 65535
MSG_CNT_MODULO = 128

# --- Path history / prediction (Part II-0) -----------------------------------
OFFSET_LL_B18_MIN, OFFSET_LL_B18_MAX = -131071, 131071
OFFSET_LL_B18_UNAVAILABLE = -131072
VERT_OFFSET_B12_MIN, VERT_OFFSET_B12_MAX = -2047, 2047
VERT_OFFSET_B12_UNAVAILABLE = -2048
TIME_OFFSET_LSB_S = 0.01
TIME_OFFSET_MIN, TIME_OFFSET_MAX = 1, 65534
TIME_OFFSET_UNAVAILABLE = 65535
PATH_HISTORY_MAX_POINTS = 23  # PathHistoryPointList SIZE(1..23)

RADIUS_LSB_M = 0.1
RADIUS_STRAIGHT = 32767
RADIUS_MIN, RADIUS_MAX = -32767, 32766
CONFIDENCE_LSB_PCT = 0.5
CONFIDENCE_MAX = 200

# --- Enumerations (index == ASN.1 value) -------------------------------------
TRANSMISSION_STATE = [
    "neutral", "park", "forwardGears", "reverseGears",
    "reserved1", "reserved2", "reserved3", "unavailable",
]
TRACTION_STATUS = ["unavailable", "off", "on", "engaged"]   # also ABS, SCS
BRAKE_BOOST = ["unavailable", "off", "on"]
AUX_BRAKES = ["unavailable", "off", "on", "reserved"]

SIREN_IN_USE = ["unavailable", "notInUse", "inUse", "reserved"]
LIGHTBAR_IN_USE = [
    "unavailable", "notInUse", "inUse", "yellowCautionLights",
    "schooldBusLights", "arrowSignsActive", "slowMovingVehicle", "freqStops",
]
MULTI_VEHICLE_RESPONSE = ["unavailable", "singleVehicle", "multiVehicle", "reserved"]
RESPONSE_TYPE = [
    "notInUseOrNotEquipped", "emergency", "nonEmergency", "pursuit",
    "stationary", "slowMoving", "stopAndGoMovement",
]

BASIC_VEHICLE_ROLE = [
    "basicVehicle", "publicTransport", "specialTransport", "dangerousGoods",
    "roadWork", "roadRescue", "emergency", "safetyCar", "none-unknown",
    "truck", "motorcycle", "roadSideSource", "police", "fire", "ambulance",
    "dot", "transit", "slowMoving", "stopNgo", "cyclist", "pedestrian",
    "nonMotorized", "military",
]

# BrakeAppliedStatus bit positions (BIT STRING SIZE(5))
WHEEL_BRAKE_BITS = ["unavailable", "leftFront", "leftRear", "rightFront", "rightRear"]

# ExteriorLights bit positions (BIT STRING SIZE(9, ...))
EXTERIOR_LIGHT_BITS = [
    "lowBeamHeadlightsOn", "highBeamHeadlightsOn", "leftTurnSignalOn",
    "rightTurnSignalOn", "hazardSignalOn", "automaticLightControlOn",
    "daytimeRunningLightsOn", "fogLightOn", "parkingLightsOn",
]

# VehicleEventFlags bit positions (BIT STRING SIZE(13, ...))
VEHICLE_EVENT_BITS = [
    "eventHazardLights", "eventStopLineViolation", "eventABSactivated",
    "eventTractionControlLoss", "eventStabilityControlactivated",
    "eventHazardousMaterials", "eventReserved1", "eventHardBraking",
    "eventLightsChanged", "eventWipersChanged", "eventFlatTire",
    "eventDisabledVehicle", "eventAirBagDeployment",
]

# --- BasicVehicleClass (0..255): emergency block 60..69 -------------------
BASIC_VEHICLE_CLASS_EMERGENCY = {
    60: "emergency-TypeUnknown",
    61: "emergency-TypeOther",
    62: "emergency-Fire-Light-Vehicle",
    63: "emergency-Fire-Heavy-Vehicle",
    64: "emergency-Fire-Paramedic-Vehicle",
    65: "emergency-Fire-Ambulance-Vehicle",
    66: "emergency-Police-Light-Vehicle",
    67: "emergency-Police-Heavy-Vehicle",
    68: "emergency-Other-Responder",
    69: "emergency-Other-Ambulance",
}
BASIC_VEHICLE_CLASS_PASSENGER_UNKNOWN = 10


def is_emergency_class(value):
    return value is not None and 60 <= int(value) <= 69


# Roles that make a vehicle an "authorized emergency vehicle" for yield logic.
ERV_ROLES = frozenset({"emergency", "police", "fire", "ambulance"})
# Roles that, with amber/caution lighting, trigger move-over (CVC 21809 covers
# tow trucks and Caltrans vehicles in addition to emergency vehicles).
MOVE_OVER_ROLES = frozenset({"roadRescue", "roadWork", "dot"}) | ERV_ROLES
CAUTION_LIGHTBAR = frozenset({"yellowCautionLights", "arrowSignsActive"})
