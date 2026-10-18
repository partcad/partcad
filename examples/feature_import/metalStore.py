# The stockist the seven milled parts' billets are bought from: 6061-T6 plate,
# sawn to the four sizes 'stock.py' works out for them.
#
# A stand-in for a real supplier's API, as 'machineShop.py' beside it is one and
# as 'csvFile.py' in 'examples/provider_store' is one for a store: it answers
# out of a table what a real stockist would answer over the wire.
#
# It exists because a made part is only as obtainable as what it is made from.
# 'pc test' asks nobody to supply a part with manufacturing instructions - the
# shop is taken at its word that it can mill one - but it does ask whether the
# billet it is milled from can be had, by asking a supplier that carries the
# billet's vendor and SKU. So every billet in 'partcad.yaml' names both, and
# this is the supplier that carries them. Without it nothing in the package
# sells the metal, and the assembly that is to be made cannot be.
#
# The shop does not sell billets, and this does not mill parts: one supplier per
# thing being bought, which is how 'pc supply' builds a cart - the billets from
# here, the work on them from the shop.

from datetime import datetime, timedelta, timezone

NOW = datetime.now(timezone.utc)

VENDOR = "example-metals"

# (vendor, SKU) -> (pieces in stock, price per piece in USD). One SKU per billet
# size, priced near enough for an example: 6061-T6 at about 15 USD a kilogram,
# plus the saw.
STOCK = {
    (VENDOR, "6061-T6 plate 135x45x18"): (40, 4.80),
    (VENDOR, "6061-T6 plate 140x50x20"): (40, 5.60),
    (VENDOR, "6061-T6 plate 180x70x26"): (20, 14.50),
    (VENDOR, "6061-T6 plate 235x95x32"): (20, 29.00),
}

if "request" not in globals():
    request = {
        "api": "avail",
    }


if __name__ == "caps":
    # What a manufacturer is asked: what can you make. A store is asked about
    # SKUs instead, and has no answer to this.
    raise Exception("Not supported by stores")

elif __name__ == "avail":
    # Whether 'count' pieces can be had, the SKU being sold in packs of
    # 'count_per_sku' - one billet each, here.
    key = (request["vendor"], request["sku"])
    if key in STOCK:
        pieces, price = STOCK[key]
        output = {
            "available": pieces * request["count_per_sku"] >= request["count"],
            "count": pieces,
            "price": price,
        }
    else:
        output = {
            "available": False,
        }

elif __name__ == "quote":
    # One line per SKU, with how many of it to order already worked out.
    price = 0.0
    for line in request["cart"]["skus"]:
        key = (line["vendor"], line["sku"])
        if key not in STOCK or STOCK[key][0] < line["count"]:
            raise Exception("Not enough stock of %s %s" % key)
        price += STOCK[key][1] * float(line["count"])

    output = {
        "qos": request["cart"]["qos"],
        "price": price,
        "expire": (NOW + timedelta(days=2)).timestamp(),
        "cartId": "aero-stock-1",
        "etaMin": (NOW + timedelta(days=2)).timestamp(),
        "etaMax": (NOW + timedelta(days=4)).timestamp(),
    }

elif __name__ == "order":
    if "cartId" not in request or request["cartId"] != "aero-stock-1":
        raise Exception("Invalid cartId")
    raise Exception("Not implemented yet: this stockist takes orders by e-mail")

else:
    raise Exception("Unknown API: {}".format(__name__))
