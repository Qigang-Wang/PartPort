import json
import unittest

from partport.catalog import CatalogClient, PartRecord


class FakeResponse:
    def __init__(self, *, data=None, text=""):
        self._data = data
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.responses.pop(0)


class CatalogTests(unittest.TestCase):
    def test_lcsc_search_maps_public_fields(self):
        response = FakeResponse(
            data={
                "code": 200,
                "result": {
                    "dataList": [
                        {
                            "productId": 9243,
                            "productCode": "C8734",
                            "productModel": "STM32F103C8T6",
                            "brandNameEn": "ST",
                            "encapStandard": "LQFP-48",
                            "stockNumber": 2993,
                            "productPriceList": [
                                {"currencyPrice": 2.0285, "currencySymbol": "$"}
                            ],
                        }
                    ]
                },
            }
        )
        client = CatalogClient(session=FakeSession([response]))
        result = client.search("STM32F103C8T6", ("lcsc",))
        self.assertEqual(result.parts[0].code, "C8734")
        self.assertEqual(result.parts[0].stock, 2993)
        self.assertEqual(result.parts[0].price, "$2.0285")

    def test_both_selected_sources_are_exposed_on_result(self):
        response = FakeResponse(
            data={
                "code": 200,
                "result": {"dataList": [{"productCode": "C1", "productId": 10}]},
            }
        )
        client = CatalogClient(session=FakeSession([response]))
        result = client.search("part", ("lcsc", "szlcsc"))
        self.assertEqual(result.parts[0].sources, ("lcsc", "szlcsc"))

    def test_szlcsc_next_data_is_parsed(self):
        props = {
            "props": {
                "pageProps": {
                    "price": 0.2335,
                    "webData": {
                        "productRecord": {
                            "productId": "372553",
                            "productCode": "C393941",
                            "productModel": "TF PUSH",
                            "productGradePlateName": "SHOU HAN(首韩)",
                            "stockNumber": 20,
                        }
                    },
                }
            }
        }
        page = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(props) + "</script>"
        client = CatalogClient(session=FakeSession([FakeResponse(text=page)]))
        part = client._sz_detail("372553")
        self.assertEqual(part.code, "C393941")
        self.assertEqual(part.price, "¥0.2335")
        self.assertEqual(part.sources, ("szlcsc",))

    def test_merge_prefers_detail_and_combines_sources(self):
        base = PartRecord("C1", model="old", sources=("lcsc",))
        detail = PartRecord("C1", model="new", manufacturer="Maker", sources=("szlcsc",))
        merged = base.merged(detail)
        self.assertEqual(merged.model, "new")
        self.assertEqual(merged.manufacturer, "Maker")
        self.assertEqual(merged.sources, ("lcsc", "szlcsc"))

    def test_detail_keeps_lcsc_large_image_when_szlcsc_has_thumbnail(self):
        client = CatalogClient(session=FakeSession([]))
        client._lcsc_detail = lambda _code: PartRecord(
            "C1", image_url="https://assets.lcsc.com/images/900x900/C1.jpg"
        )
        client._sz_detail = lambda _product_id: PartRecord(
            "C1",
            manufacturer="SZ maker",
            image_url="https://alimg.szlcsc.com/thumbnail/C1.jpg",
        )
        client._eda_previews = lambda _code: PartRecord("C1")

        detailed = client.detail(
            PartRecord("C1", product_id="1"), ("lcsc", "szlcsc")
        )

        self.assertEqual(
            detailed.image_url,
            "https://assets.lcsc.com/images/900x900/C1.jpg",
        )
        self.assertEqual(detailed.manufacturer, "SZ maker")


if __name__ == "__main__":
    unittest.main()
