"""tcg.mik.moe 采集器：product-list → product-detail → card-detail 三级链路。

接口约定见 docs/data-sources.md §1：
- 均 POST `https://tcg.mik.moe/api/v3/...`，响应包装 `{code, data, msg}`。
- `cardIndex` 必须传字符串（"001"），传整数会返回 `{code:10002}`。
- 响应校验：HTTP 200 且 body code==200 且 data 非空，否则抛 MikMoeApiError（进 question 清单）。
"""

from __future__ import annotations

from typing import Any

from ptcgdb.scrapers.http import HttpClient

BASE_URL = "https://tcg.mik.moe"
SOURCE = "mik_moe"
RAW_SUBDIR = "mikmoe"  # data/raw/ 下的落盘子目录

ENDPOINT_PRODUCT_LIST = "/api/v3/card/product-list"
ENDPOINT_PRODUCT_DETAIL = "/api/v3/card/product-detail"
ENDPOINT_CARD_DETAIL = "/api/v3/card/card-detail"


class MikMoeApiError(RuntimeError):
    """业务级失败：code != 200 或 data 为空（计为可疑，进 question 清单）。"""

    def __init__(self, endpoint: str, code: Any, msg: Any) -> None:
        super().__init__(f"{endpoint} 返回 code={code} msg={msg}")
        self.endpoint = endpoint
        self.code = code
        self.msg = msg


class MikMoeScraper:
    """三个端点的薄封装；返回完整响应包装（含 code/data/msg），由 raw 层原样落盘。"""

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def fetch_product_list(self) -> dict[str, Any]:
        """系列清单：setId / name / releaseDate / series / cardsNum（对账用）。"""
        return self._post(ENDPOINT_PRODUCT_LIST, {})

    def fetch_product_detail(self, set_id: str) -> dict[str, Any]:
        """某系列全部卡牌列表（cards 条目含 setCode / cardIndex / cardName 等）。"""
        return self._post(ENDPOINT_PRODUCT_DETAIL, {"setId": set_id})

    def fetch_card_detail(self, set_code: str, card_index: str) -> dict[str, Any]:
        """单卡全字段。cardIndex 必须是字符串（如 "001"），传整数会报 10002。"""
        if not isinstance(card_index, str):
            raise TypeError(f"cardIndex 必须是字符串，收到 {type(card_index).__name__}")
        return self._post(
            ENDPOINT_CARD_DETAIL, {"setCode": set_code, "cardIndex": card_index}
        )

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = self._http.post_json(endpoint, payload)
        if not isinstance(body, dict):
            raise MikMoeApiError(endpoint, None, f"响应体不是对象: {type(body).__name__}")
        code = body.get("code")
        data = body.get("data")
        if code != 200 or data in (None, "", [], {}):
            raise MikMoeApiError(endpoint, code, body.get("msg"))
        return body
