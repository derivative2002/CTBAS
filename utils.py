import datetime

def get_timestamp():
    return datetime.datetime.utcnow().isoformat("T", "milliseconds") + "Z"
