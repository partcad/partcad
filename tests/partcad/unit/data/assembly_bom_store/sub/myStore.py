"""A minimal store provider: what it has in stock is what 'stock.csv' lists.

Only the 'avail' API is implemented, which is all that finding a supplier for a
bill of materials asks for.
"""

import csv

if "request" not in globals():
    request = {"api": "avail"}

if __name__ == "avail":
    stock = {}
    with open(request["parameters"]["file"], newline="\n") as csvfile:
        for row in csv.DictReader(csvfile, lineterminator="\n"):
            stock[(row["vendor"], row["sku"])] = int(row["count"])

    in_stock = stock.get((request["vendor"], request["sku"]), 0)
    output = {
        "available": in_stock * request["count_per_sku"] >= request["count"],
        "count": in_stock,
    }

else:
    raise Exception("Unknown API: {}".format(__name__))
