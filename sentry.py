import os
import uuid
import hashlib
import psutil
import sentry_sdk
import socket
import time

sentry_sdk.init(
    # https://docs.sentry.io/concepts/key-terms/dsn-explainer/
    dsn="https://3a80dc66ff544e5000cb4c50751f0eca@o4508651588485120.ingest.us.sentry.io/4508651601526784",
    enable_tracing=True,
    # Set traces_sample_rate to 1.0 to capture 100% of transactions for tracing.
    traces_sample_rate=1.0,
)

# # https://develop.sentry.dev/sdk/data-model/event-payloads/user/
# # For some reason, the {{auto}} tag is not working:
# # "null - Replaced because of SDK configuration"
# sentry_sdk.set_user({"ip_address": "{{auto}}"})


sentry_sdk.set_tag("utm.source", "PartCAD")
sentry_sdk.set_tag("utm.medium", "Sentry")
sentry_sdk.set_tag("utm.campaign", "Open Source")
sentry_sdk.set_tag("utm.content", "API")

sentry_sdk.set_tag("env.remote_containers", os.environ.get("REMOTE_CONTAINERS", "false").lower() == "true")

hostname = socket.getfqdn()
print("Hostname: ", hostname)
hostname_md5 = hashlib.md5(hostname.encode()).hexdigest()
print("Hostname MD5: ", hostname_md5)
sentry_sdk.set_tag("hostname.md5", hostname_md5)

username = os.getenv("USER")
print("Username: ", username)
username_md5 = hashlib.md5(username.encode()).hexdigest()
print("Username MD5: ", username_md5)
sentry_sdk.set_tag("username.md5", username_md5)


cache_dir = os.path.expanduser("~/.cache/partcad")
os.makedirs(cache_dir, exist_ok=True)
cache_file = os.path.join(cache_dir, "id")

# Check if the UID is already cached
if os.path.exists(cache_file):
    with open(cache_file, "r") as f:
        unique_uid = f.read().strip()
else:
    # Generate a new unique UID and cache it
    unique_uid = str(uuid.uuid4())
    with open(cache_file, "w") as f:
        f.write(unique_uid)

print("Unique UID: ", unique_uid)
sentry_sdk.set_user({"id": unique_uid})

memory_rss = psutil.Process().memory_info().rss
# cpu_percent = psutil.Process().cpu_percent()
cpu_user = psutil.Process().cpu_times().user

print("Memory RSS: ", memory_rss)
# print("CPU Percent: ", cpu_percent)
print("CPU User: ", cpu_user)

sentry_sdk.set_measurement("memory.rss", memory_rss, "byte")
# sentry_sdk.set_measurement("cpu.percent", cpu_percent, "percent")
sentry_sdk.set_measurement("cpu.user", cpu_user, "second")


@sentry_sdk.trace
def slow_function():

    time.sleep(0.1)
    return "done"


@sentry_sdk.trace
def fast_function():

    time.sleep(0.05)
    return "done"


# Manually call start_profiler and stop_profiler
# to profile the code in between
sentry_sdk.profiler.start_profiler()

with sentry_sdk.start_transaction(op="process", name="Data Processing") as transaction:
    for i in range(0, 10):
        slow_function()
        fast_function()


# division_by_zero = 1 / 0

# Calls to stop_profiler are optional - if you don't stop the profiler, it will keep profiling
# your application until the process exits or stop_profiler is called.
sentry_sdk.profiler.stop_profiler()
