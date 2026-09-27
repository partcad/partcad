import csv
from datetime import datetime, timedelta, timezone
import sys

NOW = datetime.now(timezone.utc)

stock = {}


def load():
    global stock, request

    with open(request["parameters"]["file"], newline="\n") as csvfile:
        reader = csv.DictReader(csvfile, lineterminator="\n")
        for row in reader:
            stock[(row["vendor"], row["sku"])] = (
                int(row["count"]),
                float(row["price"]),
            )


if not "request" in globals():
    request = {
        "api": "caps",
    }


if __name__ == "caps":
    raise Exception("Not supported by stores")

elif __name__ == "avail":
    load()

    vendor = request["vendor"]
    sku = request["sku"]
    count_per_sku = request["count_per_sku"]
    count = request["count"]

    if (vendor, sku) in stock:
        output = {
            "available": stock[(vendor, sku)][0] * count_per_sku >= count,
            "count": stock[(vendor, sku)][0],
            "price": stock[(vendor, sku)][1],
        }
    else:
        output = {
            "available": False,
        }

elif __name__ == "quote":
    load()

    # One line per SKU, with how many of it to order already worked out: a SKU
    # that is a set of several parts is ordered once for all of them.
    price = 0
    for line in request["cart"]["skus"]:
        vendor = line["vendor"]
        sku = line["sku"]
        items = line["count"]

        if (vendor, sku) not in stock or stock[(vendor, sku)][0] < items:
            raise Exception("Not enough stock")

        price += stock[(vendor, sku)][1] * float(items)

    output = {
        "qos": request["cart"]["qos"],
        "price": price,
        "expire": (NOW + timedelta(hours=1)).timestamp(),
        "cartId": "123456",
        "etaMin": (NOW + timedelta(hours=1)).timestamp(),
        "etaMax": (NOW + timedelta(hours=2)).timestamp(),
    }

elif __name__ == "order":
    raise Exception("Not implemented")

else:
    raise Exception("Unknown API: {}".format(__name__))
