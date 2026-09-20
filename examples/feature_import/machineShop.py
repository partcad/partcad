# The shop that mills the eight parts of 'AeroAssembly_connected'.
#
# A stand-in for a real supplier's API, exactly as 'gcodeWriter.py' in
# 'examples/provider_manufacturer' is one: it answers out of a table what a real
# provider would answer over the wire. What 'pc test' asks of it is the one
# question a bill of materials depends on - can somebody make this - and the
# answer comes from 'caps' below.
#
# Nothing here is specific to these parts. A shop that mills 6061 plate will
# mill any of them, which is why the capabilities say what the shop can do
# rather than listing what it has been asked for.

from datetime import datetime, timedelta, timezone

NOW = datetime.now(timezone.utc)

# What a run of eight brackets costs here, near enough for an example: a flat
# setup plus a rate per part. A real quote reads the geometry.
SETUP = 120.0
PER_PART = 35.0

if "request" not in globals():
    request = {
        "api": "capabilities",
    }


if __name__ == "caps":
    # One material, milled from plate, in the two finishes that need no second
    # supplier.
    #
    # Every part in this package is 6061, and says so under 'properties:',
    # which is where a part read from a STEP file can say it: a 'step' part's
    # type contributes no 'material' parameter, and the parameters are where
    # PartCAD's supply cart reads one from. So what reaches this script is a
    # part with no material stated, and a part like that is accepted on the
    # strength of the process rather than matched against the table below.
    output = {
        "materials": {
            "//pub/examples/partcad/feature_import:al6061": {
                "colors": [{"name": "natural"}],
                "finishes": [{"name": "none"}, {"name": "anodized"}],
            },
        },
        "formats": ["step"],
    }

elif __name__ == "quote":
    parts = request["cart"]["parts"]
    count = sum(part["count"] for part in parts.values())
    output = {
        "qos": request["cart"]["qos"],
        "price": SETUP + PER_PART * float(count),
        "expire": (NOW + timedelta(days=7)).timestamp(),
        "cartId": "aero-1",
        "etaMin": (NOW + timedelta(days=5)).timestamp(),
        "etaMax": (NOW + timedelta(days=10)).timestamp(),
    }

elif __name__ == "order":
    if "cartId" not in request or request["cartId"] != "aero-1":
        raise Exception("Invalid cartId")
    raise Exception("Not implemented yet: this shop takes orders by e-mail")

else:
    raise Exception("Unknown API: {}".format(__name__))
