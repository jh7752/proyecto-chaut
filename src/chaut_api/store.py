from typing import Protocol


class OrderStore(Protocol):
    def put_order(self, order: dict) -> None: ...


class NoopOrderStore:
    def put_order(self, order: dict) -> None:
        return None


def create_store(table_name: str | None) -> OrderStore:
    if not table_name:
        return NoopOrderStore()

    return DynamoDbOrderStore(table_name)


class DynamoDbOrderStore:
    def __init__(self, table_name: str) -> None:
        import boto3

        self._table = boto3.resource("dynamodb").Table(table_name)

    def put_order(self, order: dict) -> None:
        self._table.put_item(Item=order)
