"""Naver Commerce API: orders, customer inquiries, and product questions of the owner's own store.

Official pages: https://apicenter.commerce.naver.com/docs/auth and, below
https://apicenter.commerce.naver.com/docs/commerce-api/current/, exchange-sellers-auth,
seller-get-last-changed-status-pay-order-seller, seller-get-product-orders-pay-order-seller,
get-customer-inquiry-pay-user, and get-comments-contents.
Only fields the app shows are kept: addresses, phone numbers, and payment means are never stored.
The operator of this server must be the owner of the store and say so with NAVER_COMMERCE_SELF_OPERATED=true;
Server/README.md gives the reason. Without it the credentials are ignored and nothing is requested.
"""

from base64 import b64encode
from datetime import datetime, timedelta
from hashlib import sha256
from os import environ
from string import ascii_lowercase, ascii_uppercase, digits
from typing import Annotated, ClassVar, Final, override

import bcrypt
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from collectors.base import (
    CollectedItem,
    Collector,
    JsonObject,
    NeedsConnectionError,
    SourceConfig,
    SourceId,
    Window,
)
from collectors.http import HttpSession, Reply, parsed
from collectors.text import MAX_BODY, MAX_TITLE, plain_text
from display import local

API: Final = "https://api.commerce.naver.com/external/v1"
SELF_OPERATED: Final = "true"
REVIEW_FIRST: Final = "네이버 심사를 통과해야 스마트스토어 자동 가져오기를 연결할 수 있어요."
MISSING: Final = "아직 이어진 스마트스토어가 없어요. 먼저 연결해 주세요."
DENIED_MESSAGE: Final = "API 권한과 스마트스토어 연결 정보가 맞는지 봐 주세요."
DENIED: Final = frozenset({401, 403})
TOKEN_DENIED: Final = frozenset({400, 401, 403})
CLOCK_MARGIN: Final = timedelta(seconds=3)
ORDER_SPAN: Final = timedelta(days=1)
DETAIL_BATCH: Final = 300
MAX_PAGES: Final = 5
INQUIRY_SIZE: Final = 200
QUESTION_SIZE: Final = 100
BCRYPT_ALPHABET: Final = "./" + ascii_uppercase + ascii_lowercase + digits
SALT_LENGTH: Final = 29
SALT_LAST_BITS: Final = 0b110000


class StoreConfig(SourceConfig):
    """The store address name shown to the owner; it grants nothing."""

    store_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")] | None = None


class CommerceModel(BaseModel):
    """A Commerce API object; unused fields are dropped here."""

    model_config: ClassVar[ConfigDict] = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Token(BaseModel):
    """An issued access token."""

    access_token: str


class ChangedOrder(CommerceModel):
    """A product order that changed."""

    product_order_id: str


class More(CommerceModel):
    """Where the next page starts."""

    more_from: str
    more_sequence: str


class ChangedData(CommerceModel):
    """One page of changed product orders."""

    last_change_statuses: list[ChangedOrder] = []
    more: More | None = None


class ChangedPage(CommerceModel):
    """The response envelope; a quiet day has no data."""

    data: ChangedData | None = None


class Order(CommerceModel):
    """Who ordered and when."""

    order_date: datetime
    orderer_id: str = ""
    orderer_name: str = ""


class ProductOrder(CommerceModel):
    """What was ordered and its state."""

    product_order_id: str
    product_name: str = ""
    product_option: str = ""
    product_order_status: str = ""
    place_order_status: str = ""
    quantity: int = 1
    total_payment_amount: int = 0


class OrderDetail(CommerceModel):
    """One product order."""

    order: Order
    product_order: ProductOrder


class OrderDetails(CommerceModel):
    """Details of the requested product orders."""

    data: list[OrderDetail] = []


class CustomerInquiry(CommerceModel):
    """A question about an order."""

    inquiry_no: int
    category: str = ""
    title: str
    inquiry_content: str
    inquiry_registration_date_time: datetime
    answered: bool
    answer_content: str | None = None
    product_name: str | None = None
    customer_id: str = ""
    customer_name: str


class InquiryPage(CommerceModel):
    """One page of customer inquiries."""

    content: list[CustomerInquiry] = []
    last: bool = True


class ProductQuestion(CommerceModel):
    """A question on a product page."""

    question_id: int
    question: str = ""
    create_date: datetime
    answered: bool = False
    answer: str | None = None
    product_name: str | None = None
    masked_writer_id: str = ""


class QuestionPage(CommerceModel):
    """One page of product questions."""

    contents: list[ProductQuestion] = []
    last: bool = True


def canonical_salt(salt: str) -> str:
    """Clear the unused bits of the last salt character: most bcrypt versions ignore them."""
    if len(salt) != SALT_LENGTH or salt[-1] not in BCRYPT_ALPHABET:
        return salt
    return salt[:-1] + BCRYPT_ALPHABET[BCRYPT_ALPHABET.index(salt[-1]) & SALT_LAST_BITS]


def signature(client_id: str, client_secret: str, timestamp: int) -> str:
    """Sign a token request: base64 of bcrypt(client_id + "_" + timestamp) salted with the secret."""
    salt = canonical_salt(client_secret)
    hashed = bcrypt.hashpw(f"{client_id}_{timestamp}".encode(), salt.encode())
    return b64encode(hashed).decode()


def person_key(identifier: str) -> str:
    """Recognize a returning buyer without keeping the platform identifier."""
    return sha256(identifier.encode()).hexdigest()[:24] if identifier else ""


def moment(value: datetime) -> str:
    """Format a time the way the API requires."""
    return local(value).isoformat(timespec="milliseconds")


def checked(reply: Reply) -> bytes:
    """Return a successful body; a refused credential needs the owner."""
    if reply.status in DENIED:
        raise NeedsConnectionError(DENIED_MESSAGE)
    return reply.expect_ok()


def order_item(detail: OrderDetail) -> CollectedItem:
    """Turn a product order into a collected item."""
    order, product = detail.order, detail.product_order
    raw: JsonObject = {
        "productOrderId": product.product_order_id, "productOrderStatus": product.product_order_status,
        "placeOrderStatus": product.place_order_status, "quantity": product.quantity,
        "totalPaymentAmount": product.total_payment_amount, "customerKey": person_key(order.orderer_id),
    }
    return CollectedItem(
        external_id=f"order:{product.product_order_id}", kind="order",
        title=plain_text(product.product_name, MAX_TITLE), body=plain_text(product.product_option, MAX_BODY),
        author=plain_text(order.orderer_name, MAX_TITLE) or None, url=None,
        published_at=order.order_date, raw=raw,
    )


def inquiry_item(entry: CustomerInquiry) -> CollectedItem:
    """Turn a customer inquiry into a collected item."""
    raw: JsonObject = {
        "answered": entry.answered, "answer": plain_text(entry.answer_content or "", MAX_BODY),
        "productName": plain_text(entry.product_name or "", MAX_TITLE),
        "customerKey": person_key(entry.customer_id), "category": plain_text(entry.category, MAX_TITLE),
    }
    return CollectedItem(
        external_id=f"inquiry:{entry.inquiry_no}", kind="inquiry", title=plain_text(entry.title, MAX_TITLE),
        body=plain_text(entry.inquiry_content, MAX_BODY),
        author=plain_text(entry.customer_name, MAX_TITLE) or None, url=None,
        published_at=entry.inquiry_registration_date_time, raw=raw,
    )


def question_item(entry: ProductQuestion) -> CollectedItem:
    """Turn a product question into a collected item."""
    raw: JsonObject = {
        "answered": entry.answered, "answer": plain_text(entry.answer or "", MAX_BODY),
        "productName": plain_text(entry.product_name or "", MAX_TITLE),
    }
    return CollectedItem(
        external_id=f"qna:{entry.question_id}", kind="inquiry", title="상품 문의",
        body=plain_text(entry.question, MAX_BODY),
        author=plain_text(entry.masked_writer_id, MAX_TITLE) or None, url=None,
        published_at=entry.create_date, raw=raw,
    )


class SmartStoreCollector(Collector[StoreConfig]):
    """Read the owner's own store through the official Commerce API."""

    source_id: ClassVar[SourceId] = "naver_smartstore"
    display_name: ClassVar[str] = "네이버 스마트스토어"
    min_interval: ClassVar[float] = 0.6

    @classmethod
    @override
    def config_model(cls) -> type[StoreConfig]:
        return StoreConfig

    @override
    def connection_problem(self) -> str | None:
        if environ.get("NAVER_COMMERCE_SELF_OPERATED") != SELF_OPERATED:
            return REVIEW_FIRST
        ready = environ.get("NAVER_COMMERCE_CLIENT_ID") and environ.get("NAVER_COMMERCE_CLIENT_SECRET")
        return None if ready else MISSING

    @override
    async def collect(self, window: Window) -> list[CollectedItem]:
        problem = self.connection_problem()
        if problem is not None:
            raise NeedsConnectionError(problem)
        async with self.gateway.connect(self.min_interval) as http:
            token = await self.issue_token(http, window.now)
            items = await self.orders(http, token, window)
            items += await self.inquiries(http, token, window)
            return items + await self.questions(http, token, window)

    async def issue_token(self, http: HttpSession, now: datetime) -> str:
        """Exchange a signed request for a token; the secret itself never leaves the server."""
        client_id = environ["NAVER_COMMERCE_CLIENT_ID"]
        timestamp = int((now - CLOCK_MARGIN).timestamp() * 1000)
        try:
            signed = signature(client_id, environ["NAVER_COMMERCE_CLIENT_SECRET"], timestamp)
        except ValueError:
            raise NeedsConnectionError(DENIED_MESSAGE) from None
        reply = await http.send(http.client.build_request("POST", f"{API}/oauth2/token", data={
            "client_id": client_id, "timestamp": str(timestamp), "grant_type": "client_credentials",
            "client_secret_sign": signed, "type": "SELF",
        }))
        if reply.status in TOKEN_DENIED:
            raise NeedsConnectionError(DENIED_MESSAGE)
        return parsed(Token, reply.expect_ok()).access_token

    async def orders(self, http: HttpSession, token: str, window: Window) -> list[CollectedItem]:
        """Read orders changed in the window, one day per request as the API requires."""
        changed: dict[str, None] = {}
        begin = window.since
        while begin < window.now:
            end = min(begin + ORDER_SPAN, window.now)
            params = {"lastChangedFrom": moment(begin), "lastChangedTo": moment(end)}
            for _ in range(MAX_PAGES):
                reply = await http.get(
                    f"{API}/pay-order/seller/product-orders/last-changed-statuses", params, token,
                )
                data = parsed(ChangedPage, checked(reply)).data or ChangedData()
                changed.update(dict.fromkeys(entry.product_order_id for entry in data.last_change_statuses))
                if data.more is None:
                    break
                params |= {"lastChangedFrom": data.more.more_from, "moreSequence": data.more.more_sequence}
            begin = end
        ids = list(changed)
        items: list[CollectedItem] = []
        for start in range(0, len(ids), DETAIL_BATCH):
            reply = await http.send(http.client.build_request(
                "POST", f"{API}/pay-order/seller/product-orders/query",
                json={"productOrderIds": ids[start:start + DETAIL_BATCH]},
                headers={"Authorization": f"Bearer {token}"},
            ))
            items += [order_item(entry) for entry in parsed(OrderDetails, checked(reply)).data]
        return items

    async def inquiries(self, http: HttpSession, token: str, window: Window) -> list[CollectedItem]:
        """Read customer inquiries registered in the window."""
        items: list[CollectedItem] = []
        for page in range(1, MAX_PAGES + 1):
            reply = await http.get(f"{API}/pay-user/inquiries", {
                "page": str(page), "size": str(INQUIRY_SIZE),
                "startSearchDate": local(window.since).date().isoformat(),
                "endSearchDate": local(window.now).date().isoformat(),
            }, token)
            found = parsed(InquiryPage, checked(reply))
            items += [inquiry_item(entry) for entry in found.content]
            if found.last:
                break
        return items

    async def questions(self, http: HttpSession, token: str, window: Window) -> list[CollectedItem]:
        """Read product questions asked in the window."""
        items: list[CollectedItem] = []
        for page in range(1, MAX_PAGES + 1):
            reply = await http.get(f"{API}/contents/qnas", {
                "page": str(page), "size": str(QUESTION_SIZE),
                "fromDate": moment(window.since), "toDate": moment(window.now),
            }, token)
            found = parsed(QuestionPage, checked(reply))
            items += [question_item(entry) for entry in found.contents]
            if found.last:
                break
        return items
