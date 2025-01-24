from datetime import datetime, timedelta, timezone

NOW = datetime.now(timezone.utc)
CYLINDER = "//pub/examples/partcad/provider_manufacturer:cylinder"

if not "request" in globals():
    request = {
        "api": "capabilities",
    }


if __name__ == "caps":
    # This is a capabilities request
    output = {
        "materials": {
            "//pub/std/manufacturing/material/plastic:pla": {
                "colors": [{"name": "red"}],
                "finishes": [{"name": "none"}],
            },
        },
        "formats": ["step"],
    }

elif __name__ == "quote":
    # Get a quote for the given parts and quantities,
    # taking the material and other parameters into account
    parts = request["cart"]["parts"]
    qos = request["cart"]["qos"]

    if CYLINDER not in parts:
        raise Exception("Only ':cylinder' is supported")
    if len(parts.keys()) != 1:
        raise Exception("Only ':cylinder' is supported")
    if parts[CYLINDER]["count"] != 1:
        raise Exception("Only one item is supported")

    output = {
        "qos": qos,
        "price": 100.0,
        "expire": (NOW + timedelta(hours=1)).timestamp(),
        "cartId": "cartId",
        "etaMin": (NOW + timedelta(hours=1)).timestamp(),
        "etaMax": (NOW + timedelta(hours=2)).timestamp(),
    }

elif __name__ == "order":
    # Place an order for the given cart (saved parts, quantities, and parameters)
    if not "cartId" in request or request["cartId"] != "cartId":
        raise Exception("Invalid cartId")

    raise Exception("Not implemented yet")

    output = {
        "etas": {},
    }
    output["etas"][CYLINDER] = (NOW + timedelta(hours=1)).timestamp()

else:
    raise Exception("Unknown API: {}".format(__name__))
